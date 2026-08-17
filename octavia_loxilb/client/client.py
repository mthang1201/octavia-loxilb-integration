"""LoxiLB REST API Client."""

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

    def __init__(self, config: Optional[cfg.ConfigOpts] = None):
        """Initialize the LoxiLB REST API client."""
        self.config = config or cfg.CONF.loxilb
        self.endpoints = self._parse_endpoints(self.config.api_endpoints)
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
            return data.get("lbServices", [])
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
