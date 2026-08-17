"""Live End-to-End Load Balancer Lifecycle Test for Octavia-LoxiLB Integration.

This test script validates the complete lifecycle against a live DevStack & LoxiLB deployment:
1. Load Balancer creation and VIP provisioning
2. Listener creation (TCP/80)
3. Pool creation (ROUND_ROBIN / TCP)
4. Member additions (10.0.0.10:8080, 10.0.0.11:8080)
5. Health Monitor creation (TCP probe)
6. Dataplane rule verification in LoxiLB REST API
7. Status tree verification in OpenStack
8. Cascade deletion and clean dataplane purge
"""

import json
import subprocess
import time
import pytest
import requests

from octavia_loxilb.client.client import LoxiLBClient


def run_cmd(cmd: str) -> str:
    """Execute a shell command inside the stack user DevStack environment."""
    full_cmd = f"sudo -u stack -H bash -lc 'source /opt/stack/devstack/openrc admin admin && {cmd}'"
    res = subprocess.run(full_cmd, shell=True, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Command '{cmd}' failed (code {res.returncode}):\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}")
    return res.stdout.strip()


def run_json_cmd(cmd: str) -> dict:
    """Execute OpenStack CLI command returning JSON formatted output."""
    output = run_cmd(f"{cmd} -f json")
    return json.loads(output) if output else {}


@pytest.mark.e2e
def test_full_loadbalancer_lifecycle():
    client = LoxiLBClient()
    assert client.health_check(), "LoxiLB dataplane container is not reachable"

    lb_name = "e2e-loxilb-lb"
    listener_name = "e2e-tcp-listener"
    pool_name = "e2e-tcp-pool"
    hm_name = "e2e-tcp-hm"

    try:
        # Step 1: Create Load Balancer
        print(f"Creating Load Balancer {lb_name}...")
        lb = run_json_cmd(f"openstack loadbalancer create --name {lb_name} --vip-subnet-id private-subnet --provider loxilb")
        lb_id = lb["id"]
        vip_address = lb.get("vip_address")
        assert lb_id, "Load Balancer ID is missing"
        time.sleep(2)

        # Wait for LB ACTIVE
        lb_show = run_json_cmd(f"openstack loadbalancer show {lb_id}")
        assert lb_show["provisioning_status"] == "ACTIVE"
        assert lb_show["operating_status"] == "ONLINE"
        vip_address = lb_show["vip_address"]

        # Step 2: Create Listener
        print(f"Creating Listener {listener_name} on port 80...")
        listener = run_json_cmd(f"openstack loadbalancer listener create --name {listener_name} --protocol TCP --protocol-port 80 {lb_id}")
        listener_id = listener["id"]
        time.sleep(2)

        # Wait for Listener ACTIVE
        l_show = run_json_cmd(f"openstack loadbalancer listener show {listener_id}")
        assert l_show["provisioning_status"] == "ACTIVE"

        # Step 3: Create Pool
        print(f"Creating Pool {pool_name}...")
        pool = run_json_cmd(f"openstack loadbalancer pool create --name {pool_name} --lb-algorithm ROUND_ROBIN --protocol TCP --listener {listener_id}")
        pool_id = pool["id"]
        time.sleep(2)

        p_show = run_json_cmd(f"openstack loadbalancer pool show {pool_id}")
        assert p_show["provisioning_status"] == "ACTIVE"

        # Step 4: Add Member 1
        print("Adding Member 1 (10.0.0.10:8080)...")
        m1 = run_json_cmd(f"openstack loadbalancer member create --subnet-id private-subnet --address 10.0.0.10 --protocol-port 8080 {pool_id}")
        time.sleep(2)

        # Step 5: Add Member 2
        print("Adding Member 2 (10.0.0.11:8080)...")
        m2 = run_json_cmd(f"openstack loadbalancer member create --subnet-id private-subnet --address 10.0.0.11 --protocol-port 8080 {pool_id}")
        time.sleep(2)

        # Step 6: Add Health Monitor
        print("Adding Health Monitor (TCP, delay 5, timeout 3, retries 3)...")
        hm = run_json_cmd(f"openstack loadbalancer healthmonitor create --name {hm_name} --type TCP --delay 5 --timeout 3 --max-retries 3 {pool_id}")
        time.sleep(2)

        # Step 7: Verify Dataplane Rules in LoxiLB
        print("Verifying LoxiLB Dataplane Rules...")
        all_rules = client.list_loadbalancers()
        assert len(all_rules) >= 1, f"Expected at least 1 rule in LoxiLB dataplane, got: {all_rules}"

        matching_rule = next(
            (r for r in all_rules if (r.get("serviceArguments", {}).get("externalIP") == vip_address and r.get("serviceArguments", {}).get("port") == 80)),
            None,
        )
        assert matching_rule is not None, f"No matching rule for VIP {vip_address}:80 in LoxiLB: {all_rules}"
        svc_args = matching_rule.get("serviceArguments", {})
        endpoints = matching_rule.get("endpoints", [])
        assert svc_args.get("protocol") == "tcp"
        assert svc_args.get("probetype") == "tcp"
        assert svc_args.get("probeport") == 8080
        assert len(endpoints) == 2

        ep_ips = {ep.get("endpointIP") for ep in endpoints}
        assert ep_ips == {"10.0.0.10", "10.0.0.11"}
        for ep in endpoints:
            assert ep.get("targetPort") == 8080
            assert ep.get("state") == "active"

        # Step 8: Verify Complete Status Tree in OpenStack
        print("Verifying OpenStack Status Tree...")
        raw_status = run_cmd(f"openstack loadbalancer status show {lb_id}")
        status_tree = json.loads(raw_status)
        lb_node = status_tree["loadbalancer"]
        assert lb_node["provisioning_status"] == "ACTIVE"
        assert lb_node["operating_status"] == "ONLINE"

        print("End-to-end configuration and dataplane validation PASSED!")

    finally:
        # Step 9: Clean Up (Cascade Deletion)
        print("Executing Cascade Deletion of Load Balancer...")
        try:
            run_cmd(f"openstack loadbalancer delete --cascade {lb_name}")
            time.sleep(3)
        except Exception as e:
            print(f"Cleanup warning: {e}")

        # Verify dataplane is clean
        remaining_rules = client.list_loadbalancers()
        matching_remaining = [
            r for r in remaining_rules
            if r.get("serviceArguments", {}).get("externalIP") == vip_address and r.get("serviceArguments", {}).get("port") == 80
        ]
        assert len(matching_remaining) == 0, f"LoxiLB dataplane rule was not cleaned up after cascade delete: {matching_remaining}"
        print("Cascade deletion and dataplane purge verified successfully!")


if __name__ == "__main__":
    test_full_loadbalancer_lifecycle()
