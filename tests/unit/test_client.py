"""Unit tests for LoxiLBClient."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from octavia_loxilb.client.client import LoxiLBClient
from octavia_loxilb.client.models import Endpoint, LoadbalanceEntry, ServiceArguments
from octavia_loxilb.common import constants, exceptions


@pytest.fixture
def client(mock_conf):
    return LoxiLBClient(config=mock_conf.loxilb)


def test_client_initialization(client):
    assert len(client.endpoints) == 1
    assert client.endpoints[0]["url"] == "http://192.168.50.111:11111"
    assert client.endpoints[0]["healthy"] is True


def test_client_create_loadbalancer_success(client):
    entry = LoadbalanceEntry(
        serviceArguments=ServiceArguments(
            externalIP="192.168.50.200",
            port=80,
            protocol="tcp",
            name="octavia-test",
        ),
        endpoints=[Endpoint(endpointIP="10.0.0.11", targetPort=8080)],
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'{"result": "success"}'
    mock_resp.json.return_value = {"result": "success"}

    with patch.object(client.session, "request", return_value=mock_resp) as mock_req:
        res = client.create_loadbalancer(entry)
        assert res == {"result": "success"}
        mock_req.assert_called_once()
        args, kwargs = mock_req.call_args
        assert kwargs["method"] == "POST"
        assert kwargs["url"] == "http://192.168.50.111:11111/netlox/v1/config/loadbalancer"
        assert kwargs["json"]["serviceArguments"]["externalIP"] == "192.168.50.200"


def test_client_get_loadbalancer_not_found(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.content = b'{"error": "not found"}'

    with patch.object(client.session, "request", return_value=mock_resp):
        res = client.get_loadbalancer("192.168.50.200", 80, "tcp")
        assert res is None


def test_client_delete_loadbalancer_success(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 204
    mock_resp.content = b""

    with patch.object(client.session, "request", return_value=mock_resp) as mock_req:
        res = client.delete_loadbalancer("192.168.50.200", 80, "tcp")
        assert res is True
        mock_req.assert_called_once()


def test_client_failover(mock_conf):
    mock_conf.set_override(
        "api_endpoints",
        ["http://10.0.0.1:11111", "http://10.0.0.2:11111"],
        group="loxilb",
    )
    failover_client = LoxiLBClient(config=mock_conf.loxilb)
    assert len(failover_client.endpoints) == 2

    def side_effect(method, url, **kwargs):
        if "10.0.0.1" in url:
            raise requests.exceptions.ConnectionError("Node 1 down")
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b'{"version": "v1.0"}'
        resp.json.return_value = {"version": "v1.0"}
        return resp

    with patch.object(failover_client.session, "request", side_effect=side_effect):
        res = failover_client.get_version()
        assert res == {"version": "v1.0"}
        assert failover_client.endpoints[0]["healthy"] is False
        assert failover_client.endpoints[1]["healthy"] is True
