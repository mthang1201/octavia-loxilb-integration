# Octavia–LoxiLB Integration Provider Driver

[![CI](https://github.com/mthang1201/octavia-loxilb-integration/actions/workflows/ci.yaml/badge.svg)](https://github.com/mthang1201/octavia-loxilb-integration/actions/workflows/ci.yaml)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-brightgreen.svg)](pyproject.toml)
[![OpenStack](https://img.shields.io/badge/OpenStack-Caracal%20%7C%20Dalmatian-red.svg)](https://docs.openstack.org/octavia/latest/)

An enterprise-grade, high-performance **OpenStack Octavia Provider Driver** powered by [LoxiLB](https://github.com/loxilb-io/loxilb) **eBPF / XDP / TC** in-kernel load balancing engine. Developed by **Viettel IDC R&D Team**.

---

## 🚀 Key Advantages

- **Ultra-Fast In-Kernel Forwarding**: Executes packet classification, NAT, and forwarding directly in Linux kernel eBPF bytecode (TC/XDP hooks) without user-kernel context switching.
- **Instant Provisioning**: Programs load balancers and listeners in **< 100 ms** via REST API and pinned BPF maps, eliminating the 2–3 minute VM boot time required by Amphora.
- **Zero Dedicated VM Overhead**: Eliminates dedicated QEMU virtual machines per load balancer, reducing compute, memory, and storage footprints by **> 95%**.
- **Real-Time Periodic Telemetry**: Atomic 64-bit kernel counters synchronize active connection tracking and byte metrics every 5 seconds via the Octavia stats socket.
- **Native OpenStack Integration**: Fully compatible with OpenStack CLI, Horizon dashboard, and Octavia Driver API specifications (`octavia-lib`).

---

## 📊 Feature Support Matrix

| Category | Feature | Status | Notes |
|---|---|---|---|
| **Protocols** | `TCP` | ✅ Supported | Full L4 TCP state tracking |
| | `UDP` | ✅ Supported | Full L4 stateless & stateful UDP |
| | `SCTP` | ✅ Supported | Native SCTP multi-homing support |
| | `HTTP` / `HTTPS` (L7) | ⚠️ Pass-through / TCP | L4 TLS termination & HTTP pass-through |
| **Algorithms** | `ROUND_ROBIN` | ✅ Supported | In-kernel fast round-robin (`rr`) |
| | `LEAST_CONNECTIONS` | ✅ Supported | Active conntrack flow tracking (`lc`) |
| **Health Monitors** | `TCP` | ✅ Supported | Active TCP SYN/ACK handshake probes |
| | `HTTP` / `HTTPS` | ✅ Supported | Configurable HTTP method, URL path, expected codes |
| | `UDP` / `SCTP` | ✅ Supported | In-kernel UDP echo / SCTP heartbeat probes |
| **Persistence** | `SOURCE_IP` | ✅ Supported | Configurable persistence conntrack timeout |
| **Telemetry** | Live Listener Stats | ✅ Supported | `bytes_in`, `bytes_out`, `total_connections`, `active_connections` |

---

## 🛠️ Quickstart Installation

### 1. Install Package
```bash
# In your Octavia virtual environment:
pip install octavia-loxilb
```

### 2. Configure `/etc/octavia/octavia.conf`
```ini
[api_settings]
enabled_provider_drivers = amphora:The Octavia Amphora driver.,loxilb:The LoxiLB eBPF provider driver.
default_provider_driver = loxilb

[loxilb]
api_endpoints = http://192.168.50.111:11111
api_timeout = 10
api_retries = 3
auth_type = none
stats_enabled = True
stats_interval = 5
default_mode = onearm
```

### 3. Restart Octavia Services
```bash
sudo systemctl restart devstack@o-api.service devstack@o-da.service
```

---

## 💻 Usage Example

```bash
# 1. Create Load Balancer with provider loxilb
openstack loadbalancer create --name web-lb --vip-subnet-id private-subnet --provider loxilb

# 2. Create Listener on port 80
openstack loadbalancer listener create --name web-lis --protocol TCP --protocol-port 80 web-lb

# 3. Create Round-Robin Pool
openstack loadbalancer pool create --name web-pool --lb-algorithm ROUND_ROBIN --protocol TCP --listener web-lis

# 4. Add Backend Members
openstack loadbalancer member create --subnet-id private-subnet --address 10.0.0.10 --protocol-port 8080 web-pool
openstack loadbalancer member create --subnet-id private-subnet --address 10.0.0.11 --protocol-port 8080 web-pool

# 5. Add Health Monitor
openstack loadbalancer healthmonitor create --name web-hm --delay 5 --timeout 3 --max-retries 3 --type TCP web-pool

# 6. View Live Listener Statistics
openstack loadbalancer listener stats show web-lis
```

---

## ⚡ Performance Benchmarks (`wrk` & `iperf3`)

Empirical testing on DevStack 2024.2 (Ubuntu 24.04 LTS, Kernel 6.8.0):

| Concurrency Level | Requests / Sec (RPS) | Latency (Avg) | Latency (p50) | Latency (p99) |
|---|---|---|---|---|
| **10 Concurrency** | **1,440.56** | 4.90 ms | 3.76 ms | 12.03 ms |
| **50 Concurrency** | **714.37** | 27.89 ms | 6.87 ms | 681.69 ms |
| **100 Concurrency** | **697.11** | 30.73 ms | 19.74 ms | 265.33 ms |

- **TCP Network Bandwidth**: **1.89 Gbits/sec**
- Detailed benchmarks: [`docs/benchmarks.md`](docs/benchmarks.md)

---

## 🧪 Testing & Validation

```bash
# Run all unit tests (40 tests, 100% pass)
pytest tests/unit/ -v

# Run live E2E lifecycle tests
pytest tests/e2e/test_live_lifecycle.py -v -m e2e

# Run live dataplane traffic & stats synchronization tests
pytest tests/e2e/test_dataplane_traffic.py -v -m e2e

# Execute automated performance benchmark suite
sudo bash scripts/run-benchmarks.sh
```

---

## 📚 Documentation

- [Architecture Guide](docs/architecture.md): Deep-dive into driver design, translators, eBPF TC hooks, and conntrack maps.
- [Operations Guide](docs/operations_guide.md): Production deployment, clustering, configuration parameters, and troubleshooting.
- [Benchmark Report](docs/benchmarks.md): Full throughput, latency, and resource utilization analysis.
- [Research Notes](docs/research/): Comprehensive research on L4/L7, BGP ECMP, and OpenStack Octavia driver specifications.

---

## 📄 License

Licensed under the [Apache License, Version 2.0](LICENSE).
