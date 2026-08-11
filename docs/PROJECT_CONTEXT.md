# Project Context

## Project
Viettel IDC internship project:
High-performance LoxiLB-based Load Balancer for OpenStack Octavia.

## Objectives

- Integrate LoxiLB with OpenStack Octavia via Provider Driver.
- Support HA.
- Support horizontal scaling.
- Study L4/L7, BGP, ECMP and eBPF.
- Benchmark throughput, CPS, RPS, latency and CPU/RAM.
- Compare against Amphora, OVN and traditional HAProxy.
- Propose architecture for large Cloud/Telco Cloud.

## Existing implementation

PyPI:
octavia-loxilb-driver 1.0.3

This implementation must be audited before developing from scratch.

Possible outcomes for each upstream component:
- REUSE
- ADAPT
- REPLACE
- NEW IMPLEMENTATION

## Target architecture

OpenStack
    ↓
Octavia
    ↓
LoxiLB Provider Driver
    ↓
LoxiLB cluster
    ↓
BGP/ECMP
    ↓
Backend workloads

## Engineering principles

- Do not rewrite existing functionality without justification.
- Preserve evidence of experiments.
- Separate control plane and dataplane.
- All claims about upstream code must be verified against source.
- Benchmark results must be reproducible.