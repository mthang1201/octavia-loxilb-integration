"""Unit tests for LoxiLB statistics retrieval and synchronization."""

from unittest.mock import MagicMock, patch
import pytest

from octavia_loxilb.client.client import LoxiLBClient
from octavia_loxilb.status.synchronizer import StatsCollector, StatusSynchronizer


def test_client_get_loadbalancer_stats_with_counters(mock_conf):
    client = LoxiLBClient(config=mock_conf.loxilb)

    mock_lb_list = [
        {
            "serviceArguments": {
                "externalIP": "10.0.0.100",
                "port": 80,
                "protocol": "tcp",
                "name": "octavia-lb1-l1",
            },
            "endpoints": [
                {
                    "endpointIP": "10.0.0.10",
                    "targetPort": 8080,
                    "weight": 1,
                    "state": "active",
                    "counter": "50:5000",
                },
                {
                    "endpointIP": "10.0.0.11",
                    "targetPort": 8080,
                    "weight": 1,
                    "state": "active",
                    "counter": "70:7000",
                },
            ],
        }
    ]

    mock_ct = [
        {
            "destinationIP": "10.0.0.100",
            "destinationPort": 80,
            "protocol": "tcp",
            "conntrackState": "tcp-est",
            "bytes": 6000,
            "packets": 60,
        },
        {
            "destinationIP": "10.0.0.100",
            "destinationPort": 80,
            "protocol": "tcp",
            "conntrackState": "closed",
            "bytes": 1000,
            "packets": 10,
        },
    ]

    with patch.object(client, "list_loadbalancers", return_value=mock_lb_list), \
         patch.object(client, "get_conntrack", return_value=mock_ct):

        stats = client.get_loadbalancer_stats("10.0.0.100", 80, "tcp")
        assert stats["bytes_in"] == 6000
        assert stats["bytes_out"] == 6000
        assert stats["active_connections"] == 1
        assert stats["total_connections"] >= 1
        assert stats["request_errors"] == 0


def test_client_get_loadbalancer_stats_empty(mock_conf):
    client = LoxiLBClient(config=mock_conf.loxilb)
    with patch.object(client, "list_loadbalancers", return_value=[]), \
         patch.object(client, "get_conntrack", return_value=[]):
        stats = client.get_loadbalancer_stats("10.0.0.100", 80, "tcp")
        assert stats["bytes_in"] == 0
        assert stats["bytes_out"] == 0
        assert stats["active_connections"] == 0
        assert stats["total_connections"] == 0


def test_client_get_all_loadbalancer_stats(mock_conf):
    client = LoxiLBClient(config=mock_conf.loxilb)
    mock_lb_list = [
        {
            "serviceArguments": {
                "externalIP": "10.0.0.100",
                "port": 80,
                "protocol": "tcp",
                "name": "octavia-lb1-listener123",
            },
            "endpoints": [
                {
                    "endpointIP": "10.0.0.10",
                    "targetPort": 8080,
                    "counter": "20:2000",
                }
            ],
        }
    ]

    with patch.object(client, "list_loadbalancers", return_value=mock_lb_list), \
         patch.object(client, "get_conntrack", return_value=[]):
        all_stats = client.get_all_loadbalancer_stats()
        assert len(all_stats) == 1
        assert all_stats[0]["name"] == "octavia-lb1-listener123"
        assert all_stats[0]["external_ip"] == "10.0.0.100"
        assert all_stats[0]["port"] == 80
        assert all_stats[0]["bytes_in"] == 1000
        assert all_stats[0]["bytes_out"] == 1000


def test_synchronizer_update_listener_statistics(mock_conf):
    mock_dlib = MagicMock()
    syncer = StatusSynchronizer(config=mock_conf.loxilb, driver_lib_instance=mock_dlib)

    payload = {
        "listeners": [
            {
                "id": "listener-1234",
                "bytes_in": 1000,
                "bytes_out": 1000,
                "active_connections": 2,
                "total_connections": 10,
                "request_errors": 0,
            }
        ]
    }

    res = syncer.update_listener_statistics(payload)
    assert res is True
    mock_dlib.update_listener_statistics.assert_called_once_with(payload)


def test_synchronizer_sync_listener_statistics(mock_conf):
    mock_dlib = MagicMock()
    syncer = StatusSynchronizer(config=mock_conf.loxilb, driver_lib_instance=mock_dlib)
    mock_client = MagicMock()
    mock_client.get_loadbalancer_stats.return_value = {
        "bytes_in": 2500,
        "bytes_out": 2500,
        "active_connections": 1,
        "total_connections": 5,
        "request_errors": 0,
    }

    res = syncer.sync_listener_statistics(
        listener_id="listener-9999",
        client=mock_client,
        external_ip="10.0.0.100",
        port=80,
        protocol="tcp",
    )
    assert res is True
    mock_dlib.update_listener_statistics.assert_called_once_with(
        {
            "listeners": [
                {
                    "id": "listener-9999",
                    "bytes_in": 2500,
                    "bytes_out": 2500,
                    "active_connections": 1,
                    "total_connections": 5,
                    "request_errors": 0,
                }
            ]
        }
    )


def test_synchronizer_sync_all_statistics(mock_conf):
    mock_dlib = MagicMock()
    syncer = StatusSynchronizer(config=mock_conf.loxilb, driver_lib_instance=mock_dlib)
    mock_client = MagicMock()
    mock_client.get_all_loadbalancer_stats.return_value = [
        {
            "name": "octavia-lb1-listenerABC",
            "external_ip": "10.0.0.100",
            "port": 80,
            "protocol": "tcp",
            "bytes_in": 1200,
            "bytes_out": 1200,
            "active_connections": 2,
            "total_connections": 6,
            "request_errors": 0,
        }
    ]

    count = syncer.sync_all_statistics(client=mock_client)
    assert count == 1
    mock_dlib.update_listener_statistics.assert_called_once_with(
        {
            "listeners": [
                {
                    "id": "listenerABC",
                    "bytes_in": 1200,
                    "bytes_out": 1200,
                    "active_connections": 2,
                    "total_connections": 6,
                    "request_errors": 0,
                }
            ]
        }
    )


def test_stats_collector_lifecycle(mock_conf):
    mock_dlib = MagicMock()
    syncer = StatusSynchronizer(config=mock_conf.loxilb, driver_lib_instance=mock_dlib)
    mock_client = MagicMock()
    mock_client.get_all_loadbalancer_stats.return_value = []

    collector = StatsCollector(status_syncer=syncer, client=mock_client, interval=1)
    collector.start()
    assert collector._thread is not None
    assert collector._thread.is_alive()
    collector.stop()
    assert collector._thread is None
