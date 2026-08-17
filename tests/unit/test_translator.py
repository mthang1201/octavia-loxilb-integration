"""Unit tests for Octavia <-> LoxiLB translator."""

import octavia_lib.api.drivers.exceptions as driver_exceptions
from octavia_lib.api.drivers import data_models
from octavia_lib.common import constants as lib_consts
import pytest

from octavia_loxilb.common import constants, exceptions
from octavia_loxilb.translation.translator import (
    generate_service_name,
    get_vip_address,
    to_loxilb_endpoint,
    to_loxilb_service,
)


def test_get_vip_address(sample_loadbalancer):
    assert get_vip_address(sample_loadbalancer) == "192.168.50.200"


def test_get_vip_address_missing():
    lb = data_models.LoadBalancer(loadbalancer_id="lb-empty")
    with pytest.raises(exceptions.LoxiLBTranslationError):
        get_vip_address(lb)


def test_generate_service_name(sample_loadbalancer, sample_listener):
    name = generate_service_name(sample_loadbalancer, sample_listener)
    assert name == "octavia-lb-1111-listener-1111"


def test_to_loxilb_endpoint():
    m = data_models.Member(
        member_id="m-1",
        address="10.0.0.15",
        protocol_port=8080,
        weight=5,
        admin_state_up=True,
    )
    ep = to_loxilb_endpoint(m, operating_status=lib_consts.ONLINE)
    assert ep.endpointIP == "10.0.0.15"
    assert ep.targetPort == 8080
    assert ep.weight == 5
    assert ep.state == "active"


def test_to_loxilb_endpoint_disabled():
    m = data_models.Member(
        member_id="m-1",
        address="10.0.0.15",
        protocol_port=8080,
        admin_state_up=False,
    )
    ep = to_loxilb_endpoint(m)
    assert ep is None


def test_to_loxilb_service_full_tree(sample_loadbalancer, sample_listener):
    entry = to_loxilb_service(sample_loadbalancer, sample_listener)
    assert entry.serviceArguments.externalIP == "192.168.50.200"
    assert entry.serviceArguments.port == 80
    assert entry.serviceArguments.protocol == "tcp"
    assert entry.serviceArguments.sel == constants.LOXILB_SEL_ROUND_ROBIN
    assert entry.serviceArguments.monitor is True
    assert entry.serviceArguments.probetype == "tcp"
    assert len(entry.endpoints) == 2
    assert entry.endpoints[0].endpointIP == "10.0.0.11"
    assert entry.endpoints[0].targetPort == 8080
    assert entry.endpoints[1].endpointIP == "10.0.0.12"
    assert entry.endpoints[1].targetPort == 8080


def test_to_loxilb_service_least_connections(sample_loadbalancer, sample_listener, sample_pool):
    sample_pool.lb_algorithm = lib_consts.LB_ALGORITHM_LEAST_CONNECTIONS
    entry = to_loxilb_service(sample_loadbalancer, sample_listener, pool=sample_pool)
    assert entry.serviceArguments.sel == constants.LOXILB_SEL_LEAST_CONNECTIONS


def test_to_loxilb_service_unsupported_protocol(sample_loadbalancer, sample_listener):
    sample_listener.protocol = lib_consts.PROTOCOL_TERMINATED_HTTPS
    with pytest.raises(driver_exceptions.UnsupportedOptionError):
        to_loxilb_service(sample_loadbalancer, sample_listener)


def test_to_loxilb_service_unsupported_algorithm(sample_loadbalancer, sample_listener, sample_pool):
    sample_pool.lb_algorithm = lib_consts.LB_ALGORITHM_SOURCE_IP_PORT
    with pytest.raises(driver_exceptions.UnsupportedOptionError):
        to_loxilb_service(sample_loadbalancer, sample_listener, pool=sample_pool)


def test_to_loxilb_service_unsupported_persistence(sample_loadbalancer, sample_listener, sample_pool):
    sample_pool.session_persistence = {"type": lib_consts.SESSION_PERSISTENCE_HTTP_COOKIE}
    with pytest.raises(driver_exceptions.UnsupportedOptionError):
        to_loxilb_service(sample_loadbalancer, sample_listener, pool=sample_pool)


def test_to_loxilb_service_unsupported_healthmonitor(sample_loadbalancer, sample_listener, sample_pool, sample_healthmonitor):
    sample_healthmonitor.type = lib_consts.HEALTH_MONITOR_TLS_HELLO
    with pytest.raises(driver_exceptions.UnsupportedOptionError):
        to_loxilb_service(
            sample_loadbalancer,
            sample_listener,
            pool=sample_pool,
            healthmonitor=sample_healthmonitor,
        )
