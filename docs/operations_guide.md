# Octavia–LoxiLB Operations & Deployment Guide

This guide describes how to deploy, configure, operate, and troubleshoot the **Octavia–LoxiLB Provider Driver** in an OpenStack production or staging environment.

---

## 1. Prerequisites

- **OpenStack**: Yoga, Antelope, Bobcat, Caracal (2024.1), Dalmatian (2024.2) or master.
- **Octavia**: Octavia API and Octavia Driver Agent running.
- **Operating System**: Ubuntu 22.04 / 24.04 LTS, Debian 12, or RHEL 9 with Linux Kernel >= 5.15 (6.x recommended).
- **LoxiLB Dataplane**: LoxiLB container or standalone cluster (v0.9.8+) with kernel eBPF/XDP support.

---

## 2. Driver Installation

Install the `octavia-loxilb` package in the Python environment where Octavia API and Octavia Driver Agent are installed:

```bash
# In DevStack / virtualenv environment:
/opt/stack/data/venv/bin/pip install octavia-loxilb

# Or in system-wide environment:
sudo pip install octavia-loxilb
```

Verify entrypoint registration:
```bash
python3 -c "import importlib.metadata; eps = importlib.metadata.entry_points(group='octavia.api.drivers'); print([ep.name for ep in eps])"
# Output should include 'loxilb'
```

---

## 3. Configuration

Add or edit `/etc/octavia/octavia.conf`:

```ini
[api_settings]
# Add loxilb to enabled provider drivers list
enabled_provider_drivers = amphora:The Octavia Amphora driver.,loxilb:The LoxiLB eBPF provider driver.
# Optionally set loxilb as the default provider:
default_provider_driver = loxilb

[loxilb]
# Comma-separated list of LoxiLB API endpoints
api_endpoints = http://192.168.50.111:11111,http://192.168.50.112:11111

# API timeout in seconds
api_timeout = 10

# Maximum retries on API communication failures
api_retries = 3

# Authentication type: none, basic, or token
auth_type = none
# username = admin
# password = secret
# token = eyJhbGciOi...

# Enable periodic listener statistics synchronization to Octavia DB
stats_enabled = True

# Stats collection polling interval (seconds)
stats_interval = 5

# Default load balancing NAT mode: onearm or fullnat
default_mode = onearm
```

Restart Octavia services:
```bash
sudo systemctl restart devstack@o-api.service devstack@o-da.service
# or in production package installs:
sudo systemctl restart octavia-api octavia-driver-agent
```

---

## 4. Operational Usage Examples

### 4.1 Create a Load Balancer with LoxiLB
```bash
openstack loadbalancer create \
  --name web-lb \
  --vip-subnet-id private-subnet \
  --provider loxilb

# Monitor provisioning status:
openstack loadbalancer show web-lb -c provisioning_status -c operating_status -c vip_address
```

### 4.2 Create Listener and Pool
```bash
# Create TCP Listener
openstack loadbalancer listener create \
  --name web-listener \
  --protocol TCP \
  --protocol-port 80 \
  web-lb

# Create Round-Robin Pool
openstack loadbalancer pool create \
  --name web-pool \
  --lb-algorithm ROUND_ROBIN \
  --protocol TCP \
  --listener web-listener
```

### 4.3 Add Backend Members and Health Monitor
```bash
# Add Backend 1
openstack loadbalancer member create \
  --subnet-id private-subnet \
  --address 10.0.0.10 \
  --protocol-port 8080 \
  web-pool

# Add Backend 2
openstack loadbalancer member create \
  --subnet-id private-subnet \
  --address 10.0.0.11 \
  --protocol-port 8080 \
  web-pool

# Add TCP Health Monitor
openstack loadbalancer healthmonitor create \
  --name web-hm \
  --delay 5 \
  --timeout 3 \
  --max-retries 3 \
  --type TCP \
  web-pool
```

### 4.4 View Live Traffic Statistics
```bash
openstack loadbalancer listener stats show web-listener
```

---

## 5. Troubleshooting & Diagnostics

### 5.1 Check Octavia Service Logs
```bash
sudo journalctl -u devstack@o-api.service -f | grep -iE 'loxilb|StatsCollector'
sudo journalctl -u devstack@o-da.service -f | grep -iE 'loxilb|StatsCollector'
```

### 5.2 Inspect LoxiLB Dataplane State
```bash
# List all active load balancer rules in LoxiLB
sudo docker exec loxilb loxicmd get lb -o wide

# Inspect active eBPF conntrack flows
sudo docker exec loxilb loxicmd get ct

# Inspect eBPF network interfaces and attached TC/XDP programs
sudo docker exec loxilb loxicmd get port
```

### 5.3 Verify Driver Sockets
Ensure Octavia Unix domain sockets are accessible:
```bash
ls -la /var/run/octavia/status.sock
ls -la /var/run/octavia/stats.sock
```
