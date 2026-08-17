"""Pytest fixtures and configuration."""

import pytest
from octavia_lib.api.drivers import data_models
from octavia_lib.common import constants as lib_consts
from oslo_config import cfg

from octavia_loxilb.common import config


@pytest.fixture
def mock_conf():
    """Fixture providing an isolated oslo.config instance with loxilb options registered."""
    conf = cfg.ConfigOpts()
    config.register_opts(conf)
    conf.set_override("api_endpoints", ["http://192.168.50.111:11111"], group="loxilb")
    conf.set_override("api_timeout", 5, group="loxilb")
    conf.set_override("api_retries", 2, group="loxilb")
    conf.set_override("api_retry_interval", 1, group="loxilb")
    conf.set_override("status_socket", "/tmp/test_status.sock", group="loxilb")
    return conf


@pytest.fixture
def sample_members():
    """Fixture providing sample Member data models."""
    m1 = data_models.Member(
        member_id="m-1111",
        pool_id="pool-1111",
        address="10.0.0.11",
        protocol_port=8080,
        weight=1,
        admin_state_up=True,
    )
    m2 = data_models.Member(
        member_id="m-2222",
        pool_id="pool-1111",
        address="10.0.0.12",
        protocol_port=8080,
        weight=2,
        admin_state_up=True,
    )
    return [m1, m2]


@pytest.fixture
def sample_healthmonitor():
    """Fixture providing a sample HealthMonitor data model."""
    return data_models.HealthMonitor(
        healthmonitor_id="hm-1111",
        pool_id="pool-1111",
        type=lib_consts.HEALTH_MONITOR_TCP,
        delay=5,
        timeout=3,
        max_retries=3,
        max_retries_down=3,
        admin_state_up=True,
    )


@pytest.fixture
def sample_pool(sample_members, sample_healthmonitor):
    """Fixture providing a sample Pool data model."""
    return data_models.Pool(
        pool_id="pool-1111",
        listener_id="listener-1111",
        loadbalancer_id="lb-1111",
        protocol=lib_consts.PROTOCOL_TCP,
        lb_algorithm=lib_consts.LB_ALGORITHM_ROUND_ROBIN,
        admin_state_up=True,
        members=sample_members,
        healthmonitor=sample_healthmonitor,
    )


@pytest.fixture
def sample_listener(sample_pool):
    """Fixture providing a sample Listener data model."""
    return data_models.Listener(
        listener_id="listener-1111",
        loadbalancer_id="lb-1111",
        protocol=lib_consts.PROTOCOL_TCP,
        protocol_port=80,
        default_pool_id="pool-1111",
        default_pool=sample_pool,
        admin_state_up=True,
    )


@pytest.fixture
def sample_loadbalancer(sample_listener):
    """Fixture providing a sample LoadBalancer data model."""
    return data_models.LoadBalancer(
        loadbalancer_id="lb-1111",
        project_id="proj-1111",
        vip_address="192.168.50.200",
        admin_state_up=True,
        listeners=[sample_listener],
    )
