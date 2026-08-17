"""Unit tests for StatusSynchronizer."""

from unittest.mock import MagicMock

from octavia_lib.common import constants as lib_consts

from octavia_loxilb.status.synchronizer import StatusSynchronizer


def test_status_synchronizer_loadbalancer(mock_conf):
    mock_dlib = MagicMock()
    syncer = StatusSynchronizer(config=mock_conf.loxilb, driver_lib_instance=mock_dlib)

    res = syncer.update_loadbalancer_status("lb-1234", provisioning_status=lib_consts.ACTIVE, operating_status=lib_consts.ONLINE)
    assert res is True
    mock_dlib.update_loadbalancer_status.assert_called_once_with(
        {"loadbalancers": [{"id": "lb-1234", "provisioning_status": "ACTIVE", "operating_status": "ONLINE"}]}
    )


def test_status_synchronizer_listener(mock_conf):
    mock_dlib = MagicMock()
    syncer = StatusSynchronizer(config=mock_conf.loxilb, driver_lib_instance=mock_dlib)

    res = syncer.update_listener_status("l-1234", provisioning_status=lib_consts.ACTIVE, operating_status=lib_consts.ONLINE)
    assert res is True
    mock_dlib.update_loadbalancer_status.assert_called_once_with(
        {"listeners": [{"id": "l-1234", "provisioning_status": "ACTIVE", "operating_status": "ONLINE"}]}
    )


def test_status_synchronizer_member(mock_conf):
    mock_dlib = MagicMock()
    syncer = StatusSynchronizer(config=mock_conf.loxilb, driver_lib_instance=mock_dlib)

    res = syncer.update_member_status("m-1234", provisioning_status=lib_consts.DELETED, operating_status=None)
    assert res is True
    mock_dlib.update_loadbalancer_status.assert_called_once_with(
        {"members": [{"id": "m-1234", "provisioning_status": "DELETED"}]}
    )
