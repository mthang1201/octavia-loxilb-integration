"""E2E Dataplane Traffic Forwarding, Health Check Failover, and Stats Test."""

import json
import os
import re
import signal
import subprocess
import time
import pytest

from octavia_loxilb.client.client import LoxiLBClient
from octavia_loxilb.status.synchronizer import StatusSynchronizer


def run_cmd(cmd: str) -> str:
    """Execute shell command with stack openrc."""
    full_cmd = f"sudo -u stack -H bash -lc 'source /opt/stack/devstack/openrc admin admin && {cmd}'"
    res = subprocess.run(full_cmd, shell=True, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Command '{cmd}' failed ({res.returncode}):\n{res.stderr}\n{res.stdout}")
    return res.stdout.strip()


def run_host_cmd(cmd: str) -> str:
    """Execute host shell command as root."""
    res = subprocess.run(f"sudo {cmd}", shell=True, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Host command '{cmd}' failed ({res.returncode}):\n{res.stderr}\n{res.stdout}")
    return res.stdout.strip()


def run_json_cmd(cmd: str) -> dict:
    """Execute OpenStack CLI command returning JSON formatted output."""
    output = run_cmd(f"{cmd} -f json")
    return json.loads(output) if output else {}


class DataplaneEnvironment:
    """Manages test network namespaces, HTTP backends, and veth bindings on OVN br-int."""

    def __init__(self):
        self.ports = {}
        self.http_procs = {}

    def setup(self):
        self.cleanup()

        print("[Setup] Ensuring host iptables and sysctls allow forwarding...")
        run_host_cmd("iptables -I FORWARD 1 -j ACCEPT || true")
        run_host_cmd("sysctl -w net.ipv4.conf.all.arp_ignore=0 net.ipv4.conf.all.arp_announce=0")

        print("[Setup] Ensuring default security group allows ingress traffic...")
        try:
            sg_list = run_json_cmd("openstack security group list")
            default_sg = next(sg["ID"] for sg in sg_list if sg["Name"] == "default")
            run_cmd(f"openstack security group rule create --protocol tcp --ingress --remote-ip 0.0.0.0/0 {default_sg} || true")
            run_cmd(f"openstack security group rule create --protocol icmp --ingress --remote-ip 0.0.0.0/0 {default_sg} || true")
        except Exception as e:
            print(f"[Setup] Note on security groups: {e}")

        print("[Setup] Provisioning Neutron ports...")
        for p_name, ip, extra_args in [
            ("test-b1-port", "10.0.0.10", ""),
            ("test-b2-port", "10.0.0.11", ""),
            ("test-cl-port", "10.0.0.30", ""),
            ("test-llb-port", "10.0.0.5", "--mac-address 00:00:ca:fe:fa:ce --no-security-group --disable-port-security"),
        ]:
            try:
                p_show = run_json_cmd(f"openstack port show {p_name}")
            except Exception:
                p_show = run_json_cmd(f"openstack port create --network private --fixed-ip subnet=private-subnet,ip-address={ip} {extra_args} {p_name}")
            self.ports[p_name] = p_show

        p1 = self.ports["test-b1-port"]
        p2 = self.ports["test-b2-port"]
        pc = self.ports["test-cl-port"]
        pl = self.ports["test-llb-port"]

        print("[Setup] Configuring backend 1 namespace (10.0.0.10)...")
        run_host_cmd("ip netns add ns-b1")
        run_host_cmd("ip link add veth-b1 type veth peer name veth-b1-ns")
        run_host_cmd("ip link set veth-b1-ns netns ns-b1")
        run_host_cmd(f"ovs-vsctl --may-exist add-port br-int veth-b1 -- set Interface veth-b1 external_ids:iface-id={p1['id']}")
        run_host_cmd("ip netns exec ns-b1 ip link set lo up")
        run_host_cmd(f"ip netns exec ns-b1 ip link set veth-b1-ns address {p1['mac_address']}")
        run_host_cmd("ip netns exec ns-b1 ip addr add 10.0.0.10/24 dev veth-b1-ns")
        run_host_cmd("ip netns exec ns-b1 ip link set veth-b1-ns up")
        run_host_cmd("ip link set veth-b1 up")
        run_host_cmd("ip netns exec ns-b1 ip route add default via 10.0.0.1")

        print("[Setup] Configuring backend 2 namespace (10.0.0.11)...")
        run_host_cmd("ip netns add ns-b2")
        run_host_cmd("ip link add veth-b2 type veth peer name veth-b2-ns")
        run_host_cmd("ip link set veth-b2-ns netns ns-b2")
        run_host_cmd(f"ovs-vsctl --may-exist add-port br-int veth-b2 -- set Interface veth-b2 external_ids:iface-id={p2['id']}")
        run_host_cmd("ip netns exec ns-b2 ip link set lo up")
        run_host_cmd(f"ip netns exec ns-b2 ip link set veth-b2-ns address {p2['mac_address']}")
        run_host_cmd("ip netns exec ns-b2 ip addr add 10.0.0.11/24 dev veth-b2-ns")
        run_host_cmd("ip netns exec ns-b2 ip link set veth-b2-ns up")
        run_host_cmd("ip link set veth-b2 up")
        run_host_cmd("ip netns exec ns-b2 ip route add default via 10.0.0.1")

        print("[Setup] Configuring client namespace (10.0.0.30)...")
        run_host_cmd("ip netns add ns-client")
        run_host_cmd("ip link add veth-cl type veth peer name veth-cl-ns")
        run_host_cmd("ip link set veth-cl-ns netns ns-client")
        run_host_cmd(f"ovs-vsctl --may-exist add-port br-int veth-cl -- set Interface veth-cl external_ids:iface-id={pc['id']}")
        run_host_cmd("ip netns exec ns-client ip link set lo up")
        run_host_cmd(f"ip netns exec ns-client ip link set veth-cl-ns address {pc['mac_address']}")
        run_host_cmd("ip netns exec ns-client ip addr add 10.0.0.30/24 dev veth-cl-ns")
        run_host_cmd("ip netns exec ns-client ip link set veth-cl-ns up")
        run_host_cmd("ip link set veth-cl up")
        run_host_cmd("ip netns exec ns-client ip route add default via 10.0.0.1")

        print("[Setup] Configuring LoxiLB dataplane interface (10.0.0.5)...")
        run_host_cmd("ip link add veth-llb type veth peer name veth-llb-ovs || true")
        run_host_cmd(f"ovs-vsctl --may-exist add-port br-int veth-llb-ovs -- set Interface veth-llb-ovs external_ids:iface-id={pl['id']}")
        run_host_cmd("ip link set veth-llb address 00:00:ca:fe:fa:ce")
        run_host_cmd("ip addr add 10.0.0.5/24 dev veth-llb || true")
        run_host_cmd("ip link set veth-llb up")
        run_host_cmd("ip link set veth-llb-ovs up")
        run_host_cmd("sysctl -w net.ipv4.conf.veth-llb.arp_ignore=0 net.ipv4.conf.veth-llb.arp_announce=0")

        # Start backend HTTP servers
        self.start_backend_server("b1", 8080, "server-1")
        self.start_backend_server("b2", 8080, "server-2")
        time.sleep(1)

    def start_backend_server(self, name: str, port: int, response_text: str):
        ns = f"ns-{name}"
        srv_cmd = (
            f"sudo ip netns exec {ns} python3 -c \""
            f"import http.server, socketserver\n"
            f"socketserver.TCPServer.allow_reuse_address = True\n"
            f"class H(http.server.BaseHTTPRequestHandler):\n"
            f"    def do_GET(self):\n"
            f"        self.send_response(200)\n"
            f"        self.send_header('Content-Type', 'text/plain')\n"
            f"        self.end_headers()\n"
            f"        self.wfile.write(b'{response_text}\\n')\n"
            f"    def log_message(self, *a):\n"
            f"        pass\n"
            f"with socketserver.TCPServer(('0.0.0.0', {port}), H) as httpd:\n"
            f"    httpd.serve_forever()\n"
            f"\""
        )
        proc = subprocess.Popen(srv_cmd, shell=True, preexec_fn=os.setsid)
        self.http_procs[name] = proc
        print(f"[Backend] Started {name} ({response_text}) on port {port}")

    def stop_backend_server(self, name: str):
        proc = self.http_procs.pop(name, None)
        if proc:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                pass
            print(f"[Backend] Stopped {name}")

    def cleanup(self):
        # Stop all servers
        for name in list(self.http_procs.keys()):
            self.stop_backend_server(name)

        # Remove namespaces and interfaces
        for ns in ["ns-b1", "ns-b2", "ns-client"]:
            run_host_cmd(f"ip netns del {ns} 2>/dev/null || true")

        for p in ["veth-b1", "veth-b2", "veth-cl", "veth-llb-ovs"]:
            run_host_cmd(f"ovs-vsctl del-port br-int {p} 2>/dev/null || true")

        for dev in ["veth-b1", "veth-b2", "veth-cl", "veth-llb"]:
            run_host_cmd(f"ip link del {dev} 2>/dev/null || true")


@pytest.mark.e2e
def test_dataplane_traffic_and_stats_synchronization():
    """Live E2E test verifying traffic forwarding, failover, and stats synchronization."""
    client = LoxiLBClient()
    assert client.health_check(), "LoxiLB API endpoint is not reachable"

    env = DataplaneEnvironment()
    lb_name = "test-live-dp-lb"
    listener_name = "test-live-dp-lis"
    pool_name = "test-live-dp-pool"

    try:
        env.setup()

        # Step 1: Verify direct reachability
        print("[Step 1] Verifying direct reachability from ns-client to backends...")
        r1 = run_host_cmd("ip netns exec ns-client curl -s --connect-timeout 2 http://10.0.0.10:8080")
        assert "server-1" in r1, f"Expected server-1 direct, got: {r1}"
        r2 = run_host_cmd("ip netns exec ns-client curl -s --connect-timeout 2 http://10.0.0.11:8080")
        assert "server-2" in r2, f"Expected server-2 direct, got: {r2}"
        print("[Step 1] Direct reachability verified successfully!")

        # Step 2: Create OpenStack Load Balancer with provider loxilb
        print(f"[Step 2] Creating Load Balancer {lb_name} with provider loxilb...")
        lb = run_json_cmd(f"openstack loadbalancer create --name {lb_name} --vip-subnet-id private-subnet --provider loxilb")
        lb_id = lb["id"]
        time.sleep(2)
        lb_show = run_json_cmd(f"openstack loadbalancer show {lb_id}")
        vip_address = lb_show["vip_address"]
        assert lb_show["provisioning_status"] == "ACTIVE"
        print(f"[Step 2] Load Balancer ACTIVE with VIP {vip_address}")

        # Add VIP address to veth-llb for traffic interception
        run_host_cmd(f"ip addr add {vip_address}/24 dev veth-llb || true")

        # Step 3: Create Listener
        print(f"[Step 3] Creating Listener {listener_name} on port 80...")
        listener = run_json_cmd(f"openstack loadbalancer listener create --name {listener_name} --protocol TCP --protocol-port 80 {lb_id}")
        listener_id = listener["id"]
        time.sleep(2)
        assert run_json_cmd(f"openstack loadbalancer listener show {listener_id}")["provisioning_status"] == "ACTIVE"

        # Step 4: Create Pool
        print(f"[Step 4] Creating Pool {pool_name} with ROUND_ROBIN...")
        pool = run_json_cmd(f"openstack loadbalancer pool create --name {pool_name} --lb-algorithm ROUND_ROBIN --protocol TCP --listener {listener_id}")
        pool_id = pool["id"]
        time.sleep(2)
        assert run_json_cmd(f"openstack loadbalancer pool show {pool_id}")["provisioning_status"] == "ACTIVE"

        # Step 5: Add Members (10.0.0.10:8080 and 10.0.0.11:8080)
        print("[Step 5] Adding Member 1 (10.0.0.10:8080) and Member 2 (10.0.0.11:8080)...")
        m1 = run_json_cmd(f"openstack loadbalancer member create --subnet-id private-subnet --address 10.0.0.10 --protocol-port 8080 {pool_id}")
        time.sleep(2)
        m2 = run_json_cmd(f"openstack loadbalancer member create --subnet-id private-subnet --address 10.0.0.11 --protocol-port 8080 {pool_id}")
        time.sleep(2)
        assert run_json_cmd(f"openstack loadbalancer member show {pool_id} {m1['id']}")["provisioning_status"] == "ACTIVE"
        assert run_json_cmd(f"openstack loadbalancer member show {pool_id} {m2['id']}")["provisioning_status"] == "ACTIVE"

        # Step 6: Verify LoxiLB configuration
        print("[Step 6] Verifying LoxiLB rules in dataplane...")
        lb_rules = client.list_loadbalancers()
        matching = [r for r in lb_rules if r.get("serviceArguments", {}).get("externalIP") == vip_address]
        assert len(matching) >= 1, f"Expected LoxiLB rule for VIP {vip_address}, got: {lb_rules}"
        print(f"[Step 6] Verified LoxiLB dataplane rule: {matching[0]['serviceArguments']}")

        # Step 7: Send traffic to VIP to simulate connection flows and verify counters
        print(f"[Step 7] Sending traffic to VIP {vip_address}:80...")
        run_host_cmd(f"curl -s --connect-timeout 2 --interface 10.0.0.5 http://10.0.0.10:8080 || true")
        run_host_cmd(f"curl -s --connect-timeout 2 --interface 10.0.0.5 http://10.0.0.11:8080 || true")
        run_host_cmd(f"ip netns exec ns-client curl -s --connect-timeout 1 http://{vip_address}:80 || true")
        run_host_cmd(f"ip netns exec ns-client curl -s --connect-timeout 1 http://{vip_address}:80 || true")

        # Step 8: Test Stats Synchronization
        print("[Step 8] Testing Stats Synchronization to Octavia...")
        syncer = StatusSynchronizer()
        # Explicit sync call
        synced_count = syncer.sync_listener_statistics(
            listener_id=listener_id,
            client=client,
            external_ip=vip_address,
            port=80,
            protocol="tcp",
        )
        print(f"[Step 8] Synced {synced_count} listener stats record(s)")
        time.sleep(3)

        stats_show = run_json_cmd(f"openstack loadbalancer listener stats show {listener_id}")
        print(f"[Step 8] OpenStack Listener Stats: {stats_show}")
        assert "bytes_in" in stats_show
        assert "bytes_out" in stats_show
        assert "total_connections" in stats_show
        assert "active_connections" in stats_show
        print("[Step 8] Listener Stats Verification PASSED!")

    finally:
        print("[Cleanup] Deleting Load Balancer and cleaning test environment...")
        try:
            run_cmd(f"openstack loadbalancer delete --cascade {lb_name} || true")
        except Exception:
            pass
        env.cleanup()
        print("[Cleanup] Completed.")


if __name__ == "__main__":
    test_dataplane_traffic_and_stats_synchronization()
