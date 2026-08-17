"""Unit tests for LoxiLBProviderDriver."""

from unittest.mock import MagicMock

import octavia_lib.api.drivers.exceptions as driver_exceptions
from octavia_lib.api.drivers import data_models
from octavia_lib.common import constants as lib_consts
import pytest

from octavia_loxilb.driver import LoxiLBProviderDriver


@pytest.fixture
def driver_mocks():
    mock_client = MagicMock()
    mock_syncer = MagicMock()
    mock_dlib = MagicMock()
    return mock_client, mock_syncer, mock_dlib


@pytest.fixture
def driver(driver_mocks):
    mock_client, mock_syncer, mock_dlib = driver_mocks
    return LoxiLBProviderDriver(
        client=mock_client,
        status_syncer=mock_syncer,
        driver_lib_instance=mock_dlib,
    )


def test_driver_loadbalancer_create(driver, driver_mocks, sample_loadbalancer):
    mock_client, mock_syncer, _ = driver_mocks
    driver.loadbalancer_create(sample_loadbalancer)
    mock_client.create_loadbalancer.assert_called_once()
    mock_syncer.update_loadbalancer_status.assert_called_once_with(
        "lb-1111", provisioning_status=lib_consts.ACTIVE, operating_status=lib_consts.ONLINE
    )


def test_driver_loadbalancer_delete(driver, driver_mocks, sample_loadbalancer):
    mock_client, mock_syncer, _ = driver_mocks
    driver.loadbalancer_delete(sample_loadbalancer)
    mock_syncer.update_loadbalancer_status.assert_called_once_with(
        "lb-1111", provisioning_status=lib_consts.DELETED
    )


def test_driver_listener_create(driver, driver_mocks, sample_loadbalancer, sample_listener):
    mock_client, mock_syncer, mock_dlib = driver_mocks
    mock_dlib.get_loadbalancer.return_value = sample_loadbalancer
    driver.listener_create(sample_listener)
    mock_client.create_loadbalancer.assert_called_once()
    mock_syncer.update_listener_status.assert_called_once_with(
        "listener-1111", provisioning_status=lib_consts.ACTIVE, operating_status=lib_consts.ONLINE, lb_id="lb-1111"
    )


def test_driver_listener_delete(driver, driver_mocks, sample_loadbalancer, sample_listener):
    mock_client, mock_syncer, mock_dlib = driver_mocks
    mock_dlib.get_loadbalancer.return_value = sample_loadbalancer
    driver.listener_delete(sample_listener)
    mock_client.delete_loadbalancer.assert_called_once_with(
        external_ip="192.168.50.200", port=80, protocol="tcp"
    )
    mock_syncer.update_listener_status.assert_called_once_with(
        "listener-1111", provisioning_status=lib_consts.DELETED, lb_id="lb-1111"
    )


def test_driver_pool_create(driver, driver_mocks, sample_loadbalancer, sample_listener, sample_pool):
    mock_client, mock_syncer, mock_dlib = driver_mocks
    mock_dlib.get_loadbalancer.return_value = sample_loadbalancer
    mock_dlib.get_listener.return_value = sample_listener
    driver.pool_create(sample_pool)
    mock_client.create_loadbalancer.assert_called_once()
    mock_syncer.update_pool_status.assert_called_once_with(
        "pool-1111", provisioning_status=lib_consts.ACTIVE, operating_status=lib_consts.ONLINE, lb_id="lb-1111", listener_id="listener-1111"
    )


def test_driver_member_batch_update(driver, driver_mocks, sample_loadbalancer, sample_listener, sample_pool, sample_members):
    mock_client, mock_syncer, mock_dlib = driver_mocks
    mock_dlib.get_pool.return_value = sample_pool
    mock_dlib.get_loadbalancer.return_value = sample_loadbalancer
    mock_dlib.get_listener.return_value = sample_listener

    driver.member_batch_update("pool-1111", sample_members)
    mock_client.create_loadbalancer.assert_called_once()
    mock_syncer.update_status.assert_called_once()


def test_driver_health_monitor_create(driver, driver_mocks, sample_loadbalancer, sample_listener, sample_pool, sample_healthmonitor):
    mock_client, mock_syncer, mock_dlib = driver_mocks
    mock_dlib.get_pool.return_value = sample_pool
    mock_dlib.get_loadbalancer.return_value = sample_loadbalancer
    mock_dlib.get_listener.return_value = sample_listener

    driver.health_monitor_create(sample_healthmonitor)
    mock_client.create_loadbalancer.assert_called_once()
    mock_syncer.update_healthmonitor_status.assert_called_once_with(
        "hm-1111", provisioning_status=lib_consts.ACTIVE, operating_status=lib_consts.ONLINE, lb_id="lb-1111", pool_id="pool-1111", listener_id="listener-1111"
    )


def test_driver_l7_unsupported(driver):
    with pytest.raises(driver_exceptions.NotImplementedError):
        driver.l7policy_create(data_models.L7Policy(l7policy_id="l7-1"))

    with pytest.raises(driver_exceptions.NotImplementedError):
        driver.l7rule_create(data_models.L7Rule(l7rule_id="r-1"))


def test_driver_metadata_validation(driver):
    assert driver.validate_flavor({"name": "test"}) is True
    assert driver.validate_availability_zone({"name": "zone-1"}) is True
    with pytest.raises(driver_exceptions.NotImplementedError):
        driver.create_vip_port("lb-1", "p-1", {"ip_address": "10.0.0.1"})
