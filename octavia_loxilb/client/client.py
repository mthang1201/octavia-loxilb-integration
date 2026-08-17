"""LoxiLB REST API Client."""

import os
from typing import Any, Optional
from urllib.parse import urlparse

from oslo_config import cfg
from oslo_log import log as logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from octavia_loxilb.client.models import LoadbalanceEntry
from octavia_loxilb.common import constants, exceptions

LOG = logging.getLogger(__name__)


class LoxiLBClient:
    """Client for communicating with the LoxiLB REST API."""

    def __init__(self, config: Optional[Any] = None):
        """Initialize the LoxiLB REST API client."""
        if config is None:
            try:
                from octavia_loxilb.common.config import register_opts
                register_opts(cfg.CONF)
            except (cfg.DuplicateOptError, cfg.ArgsAlreadyParsedError):
                pass
            if not getattr(cfg.CONF, "config_file", None) and os.path.exists("/etc/octavia/octavia.conf"):
                try:
                    cfg.CONF(["--config-file", "/etc/octavia/octavia.conf"])
                except Exception:
                    pass
            self.config = getattr(cfg.CONF, "loxilb", None)
        else:
            self.config = config

        raw_endpoints = getattr(self.config, "api_endpoints", ["http://127.0.0.1:11111"]) if self.config else ["http://127.0.0.1:11111"]
        self.endpoints = self._parse_endpoints(raw_endpoints)
        self.current_endpoint_index = 0
        self.session = self._create_session()
        self._setup_authentication()

    def _parse_endpoints(self, endpoints: list[str]) -> list[dict[str, Any]]:
        """Parse and validate API endpoint URLs."""
        parsed_endpoints = []
        for ep in endpoints:
            try:
                parsed = urlparse(ep)
                if not parsed.scheme or not parsed.netloc:
                    raise ValueError(f"Invalid URL structure in endpoint '{ep}'")
                parsed_endpoints.append(
                    {
                        "url": ep.rstrip("/"),
                        "host": parsed.hostname,
                        "port": parsed.port or (443 if parsed.scheme == "https" else constants.DEFAULT_API_PORT),
                        "scheme": parsed.scheme,
                        "healthy": True,
                    }
                )
            except Exception as e:
                LOG.error("Failed to parse endpoint URL %s: %s", ep, e)
                raise exceptions.LoxiLBConfigurationException("api_endpoints", ep, str(e))

        if not parsed_endpoints:
            raise exceptions.LoxiLBConfigurationException(
                "api_endpoints", "", "No valid endpoints configured"
            )
        return parsed_endpoints

    def _create_session(self) -> requests.Session:
        """Create a requests session with connection pooling and retries."""
        session = requests.Session()
        retry_strategy = Retry(
            total=self.config.api_retries,
            backoff_factor=self.config.api_retry_interval,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "PUT", "DELETE", "OPTIONS", "TRACE", "POST"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=20)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.headers.update(
            {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": f"octavia-loxilb/{constants.DRIVER_VERSION}",
            }
        )
        return session

    def _setup_authentication(self) -> None:
        """Configure authentication headers or certificates on the session."""
        auth_type = getattr(self.config, "auth_type", constants.AUTH_TYPE_NONE)

        if auth_type == constants.AUTH_TYPE_BASIC:
            username = getattr(self.config, "username", "")
            password = getattr(self.config, "password", "")
            if not username or not password:
                raise exceptions.LoxiLBConfigurationException(
                    "auth_type", auth_type, "Basic auth requires username and password"
                )
            self.session.auth = (username, password)

        elif auth_type == constants.AUTH_TYPE_TOKEN:
            token = getattr(self.config, "api_token", "")
            if not token:
                raise exceptions.LoxiLBConfigurationException(
                    "auth_type", auth_type, "Token auth requires api_token"
                )
            self.session.headers["Authorization"] = f"Bearer {token}"

        elif auth_type == constants.AUTH_TYPE_TLS:
            cert_file = getattr(self.config, "tls_client_cert_file", "")
            key_file = getattr(self.config, "tls_client_key_file", "")
            if not cert_file or not key_file:
                raise exceptions.LoxiLBConfigurationException(
                    "auth_type", auth_type, "TLS auth requires client cert and key files"
                )
            self.session.cert = (cert_file, key_file)

        ca_file = getattr(self.config, "tls_ca_cert_file", "")
        verify = getattr(self.config, "tls_verify_cert", True)
        self.session.verify = ca_file if ca_file else verify

    def _get_active_endpoint(self) -> dict[str, Any]:
        """Get the current active endpoint, failing over if necessary."""
        num_endpoints = len(self.endpoints)
        for i in range(num_endpoints):
            idx = (self.current_endpoint_index + i) % num_endpoints
            if self.endpoints[idx]["healthy"]:
                self.current_endpoint_index = idx
                return self.endpoints[idx]

        # If all marked unhealthy, reset and try the first one
        LOG.warning("All LoxiLB endpoints marked unhealthy; resetting health status to retry.")
        for ep in self.endpoints:
            ep["healthy"] = True
        self.current_endpoint_index = 0
        return self.endpoints[0]

    def _request(
        self,
        method: str,
        path: str,
        data: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> requests.Response:
        """Perform an HTTP request against LoxiLB with failover and error translation."""
        attempts = 0
        max_attempts = len(self.endpoints)
        last_error: Optional[Exception] = None

        while attempts < max_attempts:
            endpoint = self._get_active_endpoint()
            url = f"{endpoint['url']}{path}"
            timeout = getattr(self.config, "api_timeout", constants.DEFAULT_API_TIMEOUT)

            try:
                LOG.debug("LoxiLB API request %s %s (payload: %s)", method, url, data)
                response = self.session.request(
                    method=method,
                    url=url,
                    json=data,
                    params=params,
                    timeout=timeout,
                )
                LOG.debug("LoxiLB API response [%s]: %s", response.status_code, response.text)

                if response.status_code in [200, 201, 202, 204]:
                    return response
                elif response.status_code == 404:
                    raise exceptions.LoxiLBNotFoundException(
                        resource_type="resource",
                        resource_id=path,
                        endpoint=endpoint["url"],
                    )
                elif response.status_code == 409:
                    raise exceptions.LoxiLBConflictException(
                        resource_type="resource",
                        resource_id=path,
                        conflict_reason=response.text,
                    )
                elif response.status_code in [401, 403]:
                    raise exceptions.LoxiLBAuthenticationException(
                        endpoint=endpoint["url"],
                        auth_type=getattr(self.config, "auth_type", constants.AUTH_TYPE_NONE),
                    )
                else:
                    raise exceptions.LoxiLBAPIException(
                        message=f"LoxiLB API error: {response.text}",
                        status_code=response.status_code,
                        response_body=response.text,
                        endpoint=endpoint["url"],
                    )

            except (exceptions.LoxiLBNotFoundException, exceptions.LoxiLBConflictException):
                # Specific 404/409 responses from the active server are authoritative
                raise
            except requests.exceptions.Timeout as e:
                endpoint["healthy"] = False
                last_error = exceptions.LoxiLBTimeoutException(
                    endpoint=endpoint["url"],
                    timeout_value=timeout,
                    operation=f"{method} {path}",
                )
                LOG.warning("Timeout connecting to %s: %s", endpoint["url"], e)
            except requests.exceptions.ConnectionError as e:
                endpoint["healthy"] = False
                last_error = exceptions.LoxiLBConnectionException(
                    endpoint=endpoint["url"], original_exception=str(e)
                )
                LOG.warning("Connection error on %s: %s", endpoint["url"], e)
            except Exception as e:
                endpoint["healthy"] = False
                last_error = exceptions.LoxiLBAPIException(
                    message=f"Unexpected error calling LoxiLB: {e}",
                    endpoint=endpoint["url"],
                )
                LOG.warning("Request exception on %s: %s", endpoint["url"], e)

            attempts += 1

        if last_error:
            raise last_error
        raise exceptions.LoxiLBConnectionException(
            endpoint=self.endpoints[0]["url"], original_exception="All endpoints failed"
        )

    # Public API operations

    def get_version(self) -> dict[str, Any]:
        """Fetch LoxiLB version and status."""
        response = self._request("GET", constants.API_PATH_STATUS)
        return response.json() if response.content else {}

    def health_check(self) -> bool:
        """Check if LoxiLB is reachable and healthy."""
        try:
            res = self.get_version()
            return bool(res)
        except Exception as e:
            LOG.debug("LoxiLB health check failed: %s", e)
            return False

    def create_loadbalancer(self, entry: LoadbalanceEntry | dict[str, Any]) -> dict[str, Any]:
        """Create or update a load balancer service rule in LoxiLB."""
        payload = entry.to_dict() if isinstance(entry, LoadbalanceEntry) else entry
        LOG.info("Creating LoxiLB loadbalancer service rule: %s", payload.get("serviceArguments", {}).get("name"))
        response = self._request("POST", constants.API_PATH_LOADBALANCER, data=payload)
        return response.json() if response.content else {}

    def list_loadbalancers(self) -> list[dict[str, Any]]:
        """List all configured load balancer services in LoxiLB."""
        try:
            response = self._request("GET", constants.API_PATH_LOADBALANCER_ALL)
            data = response.json() if response.content else {}
            return data.get("lbAttr") or data.get("lbServices") or []
        except exceptions.LoxiLBNotFoundException:
            return []

    def get_loadbalancer(self, external_ip: str, port: int, protocol: str) -> Optional[dict[str, Any]]:
        """Get a specific load balancer service rule by external IP, port, and protocol."""
        path = f"{constants.API_PATH_LOADBALANCER}/externalipaddress/{external_ip}/port/{port}/protocol/{protocol}"
        try:
            response = self._request("GET", path)
            return response.json() if response.content else None
        except exceptions.LoxiLBNotFoundException:
            return None

    def delete_loadbalancer(self, external_ip: str, port: int, protocol: str) -> bool:
        """Delete a load balancer service rule by external IP, port, and protocol."""
        path = f"{constants.API_PATH_LOADBALANCER}/externalipaddress/{external_ip}/port/{port}/protocol/{protocol}"
        try:
            self._request("DELETE", path)
            return True
        except exceptions.LoxiLBNotFoundException:
            LOG.debug("LoxiLB service %s:%s/%s already deleted", external_ip, port, protocol)
            return True

    def delete_loadbalancer_by_name(self, name: str) -> bool:
        """Delete a load balancer service rule by name."""
        path = f"{constants.API_PATH_LOADBALANCER}/name/{name}"
        try:
            self._request("DELETE", path)
            return True
        except exceptions.LoxiLBNotFoundException:
            LOG.debug("LoxiLB service rule '%s' already deleted", name)
            return True

    def get_endpoint_states(self) -> list[dict[str, Any]]:
        """Get host health states for backend endpoints."""
        try:
            response = self._request("GET", constants.API_PATH_ENDPOINT_HOST_STATE)
            data = response.json() if response.content else {}
            return data.get("hostState", [])
        except exceptions.LoxiLBNotFoundException:
            return []

    def get_conntrack(self) -> list[dict[str, Any]]:
        """Get active and historical conntrack session entries."""
        try:
            response = self._request("GET", constants.API_PATH_CONNTRACK_ALL)
            data = response.json() if response.content else {}
            return data.get("ctAttr", [])
        except exceptions.LoxiLBNotFoundException:
            return []

    def get_loadbalancer_stats(
        self, external_ip: str, port: int, protocol: str = "tcp"
    ) -> dict[str, int]:
        """Retrieve aggregated statistics for a specific load balancer service."""
        rules = self.list_loadbalancers()
        matching_rule = next(
            (
                r
                for r in rules
                if str(r.get("serviceArguments", {}).get("externalIP")) == str(external_ip)
                and int(r.get("serviceArguments", {}).get("port", 0)) == int(port)
                and str(r.get("serviceArguments", {}).get("protocol", "")).lower() == str(protocol).lower()
            ),
            None,
        )

        if not matching_rule:
            return {
                "bytes_in": 0,
                "bytes_out": 0,
                "active_connections": 0,
                "total_connections": 0,
                "request_errors": 0,
            }

        total_bytes = 0
        total_packets = 0
        endpoints = matching_rule.get("endpoints", [])
        for ep in endpoints:
            counter_str = ep.get("counter", "0:0")
            try:
                parts = str(counter_str).split(":")
                if len(parts) == 2:
                    pkts = int(parts[0])
                    bts = int(parts[1])
                    total_packets += pkts
                    total_bytes += bts
            except (ValueError, TypeError):
                pass

        # Calculate active connections and flow bytes from conntrack
        ct_entries = self.get_conntrack()
        active_conns = 0
        ct_bytes = 0
        ct_pkts = 0
        for ct in ct_entries:
            dst_ip = ct.get("destinationIP")
            dst_port = ct.get("destinationPort")
            proto = str(ct.get("protocol", "")).lower()
            if (
                dst_ip == str(external_ip)
                and dst_port == int(port)
                and proto == str(protocol).lower()
            ):
                ct_bytes += int(ct.get("bytes", 0))
                ct_pkts += int(ct.get("packets", 0))
                state = str(ct.get("conntrackState", "")).lower()
                if "est" in state or "active" in state or "open" in state:
                    active_conns += 1

        # Use the maximum of endpoint counters or conntrack counters
        effective_bytes = max(total_bytes, ct_bytes)
        effective_packets = max(total_packets, ct_pkts)

        # In FullNAT / One-Arm load balancing, bytes_in is ingress request data
        # and bytes_out is egress response data. We estimate symmetric or split flow.
        bytes_in = effective_bytes // 2 if effective_bytes > 0 else 0
        bytes_out = effective_bytes - bytes_in if effective_bytes > 0 else 0
        if bytes_in == 0 and effective_bytes > 0:
            bytes_in = effective_bytes
            bytes_out = effective_bytes

        total_conns = max(active_conns, (effective_packets // 4) if effective_packets >= 4 else (1 if effective_packets > 0 else 0))

        return {
            "bytes_in": bytes_in,
            "bytes_out": bytes_out,
            "active_connections": active_conns,
            "total_connections": total_conns,
            "request_errors": 0,
        }

    def get_all_loadbalancer_stats(self) -> list[dict[str, Any]]:
        """Retrieve aggregated statistics for all configured load balancers."""
        rules = self.list_loadbalancers()
        conntrack = self.get_conntrack()
        stats_list = []

        for rule in rules:
            svc = rule.get("serviceArguments", {})
            ext_ip = svc.get("externalIP")
            port = svc.get("port")
            proto = svc.get("protocol", "tcp")
            name = svc.get("name", "")

            if not ext_ip or port is None:
                continue

            total_bytes = 0
            total_packets = 0
            for ep in rule.get("endpoints", []):
                counter_str = ep.get("counter", "0:0")
                try:
                    parts = str(counter_str).split(":")
                    if len(parts) == 2:
                        total_packets += int(parts[0])
                        total_bytes += int(parts[1])
                except (ValueError, TypeError):
                    pass

            active_conns = 0
            ct_bytes = 0
            ct_pkts = 0
            for ct in conntrack:
                if (
                    ct.get("destinationIP") == str(ext_ip)
                    and ct.get("destinationPort") == int(port)
                    and str(ct.get("protocol", "")).lower() == str(proto).lower()
                ):
                    ct_bytes += int(ct.get("bytes", 0))
                    ct_pkts += int(ct.get("packets", 0))
                    state = str(ct.get("conntrackState", "")).lower()
                    if "est" in state or "active" in state or "open" in state:
                        active_conns += 1

            effective_bytes = max(total_bytes, ct_bytes)
            effective_packets = max(total_packets, ct_pkts)

            bytes_in = effective_bytes // 2 if effective_bytes > 0 else 0
            bytes_out = effective_bytes - bytes_in if effective_bytes > 0 else 0
            if bytes_in == 0 and effective_bytes > 0:
                bytes_in = effective_bytes
                bytes_out = effective_bytes

            total_conns = max(
                active_conns,
                (effective_packets // 4) if effective_packets >= 4 else (1 if effective_packets > 0 else 0),
            )

            stats_list.append(
                {
                    "name": name,
                    "external_ip": ext_ip,
                    "port": int(port),
                    "protocol": proto,
                    "bytes_in": bytes_in,
                    "bytes_out": bytes_out,
                    "active_connections": active_conns,
                    "total_connections": total_conns,
                    "request_errors": 0,
                }
            )

        return stats_list
