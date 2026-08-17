"""Status Synchronizer for Octavia LoxiLB Provider Driver."""

import os
import re
import threading
from typing import Any, Optional

from octavia_lib.api.drivers import driver_lib
from octavia_lib.api.drivers import exceptions as driver_exceptions
from octavia_lib.common import constants as lib_consts
from oslo_config import cfg
from oslo_log import log as logging

LOG = logging.getLogger(__name__)


class StatusSynchronizer:
    """Synchronizes status from the LoxiLB driver back to Octavia via DriverLibrary."""

    def __init__(self, config: Optional[Any] = None, driver_lib_instance: Optional[Any] = None):
        """Initialize the StatusSynchronizer."""
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
        self._driver_lib = driver_lib_instance
        self._driver_lib_checked = False

    @property
    def driver_lib(self) -> Optional[driver_lib.DriverLibrary]:
        """Lazily initialize and return DriverLibrary instance."""
        if self._driver_lib is None and not self._driver_lib_checked:
            status_sock = getattr(self.config, "status_socket", "/var/run/octavia/status.sock")
            stats_sock = getattr(self.config, "stats_socket", "/var/run/octavia/stats.sock")
            get_sock = getattr(self.config, "get_socket", "/var/run/octavia/get.sock")

            # Check if status socket file exists before attempting connection to avoid retry timeout
            if not os.path.exists(status_sock):
                LOG.debug("Status socket %s does not exist; skipping DriverLibrary socket initialization", status_sock)
                self._driver_lib_checked = True
                return None

            try:
                self._driver_lib = driver_lib.DriverLibrary(
                    status_socket=status_sock,
                    stats_socket=stats_sock,
                    get_socket=get_sock,
                )
            except Exception as e:
                LOG.warning("Could not connect to Octavia DriverLibrary sockets: %s", e)
                self._driver_lib = None
            finally:
                self._driver_lib_checked = True

        return self._driver_lib

    def _send_update(self, status: dict[str, list[dict[str, Any]]], delay: float = 0.0) -> bool:
        """Internal helper to transmit status update through DriverLibrary."""
        if delay > 0:
            import time
            time.sleep(delay)
        LOG.debug("Sending status update to Octavia: %s", status)
        lib = self.driver_lib
        if lib is None:
            LOG.debug("DriverLibrary socket unavailable; status update skipped: %s", status)
            return False

        try:
            lib.update_loadbalancer_status(status)
            return True
        except driver_exceptions.UpdateStatusError as e:
            LOG.warning("Octavia rejected status update: %s", e)
            return False
        except Exception as e:
            LOG.debug("Status socket transmission skipped/failed: %s", e)
            return False

    def update_status(self, status: dict[str, list[dict[str, Any]]], async_delay: float = 0.15) -> bool:
        """Send a status dictionary to Octavia via the status socket.

        Args:
            status: Formatted dictionary containing status updates for resources.
            async_delay: Delay in seconds before sending (executed in a background thread
                         to allow the API server transaction to commit first).

        Returns:
            bool: True if status update scheduled/sent, False if socket unavailable.
        """
        # In unit tests with a mock DriverLibrary instance, run synchronously
        if self._driver_lib is not None and not isinstance(self._driver_lib, driver_lib.DriverLibrary):
            return self._send_update(status, delay=0.0)

        if async_delay > 0:
            import threading
            t = threading.Thread(target=self._send_update, args=(status, async_delay))
            t.daemon = True
            t.start()
            return True
        return self._send_update(status, delay=0.0)

    def update_loadbalancer_status(
        self,
        lb_id: str,
        provisioning_status: str = lib_consts.ACTIVE,
        operating_status: Optional[str] = lib_consts.ONLINE,
    ) -> bool:
        """Update single load balancer status."""
        entry: dict[str, Any] = {
            "id": lb_id,
            "provisioning_status": provisioning_status,
        }
        if operating_status is not None:
            entry["operating_status"] = operating_status
        return self.update_status({"loadbalancers": [entry]})

    def update_listener_status(
        self,
        listener_id: str,
        provisioning_status: str = lib_consts.ACTIVE,
        operating_status: Optional[str] = lib_consts.ONLINE,
        lb_id: Optional[str] = None,
    ) -> bool:
        """Update single listener status and optionally parent loadbalancer."""
        entry: dict[str, Any] = {
            "id": listener_id,
            "provisioning_status": provisioning_status,
        }
        if operating_status is not None:
            entry["operating_status"] = operating_status
        payload = {"listeners": [entry]}
        if lb_id:
            payload["loadbalancers"] = [{"id": lb_id, "provisioning_status": lib_consts.ACTIVE}]
        return self.update_status(payload)

    def update_pool_status(
        self,
        pool_id: str,
        provisioning_status: str = lib_consts.ACTIVE,
        operating_status: Optional[str] = lib_consts.ONLINE,
        lb_id: Optional[str] = None,
        listener_id: Optional[str] = None,
    ) -> bool:
        """Update single pool status and optionally parent listener and loadbalancer."""
        entry: dict[str, Any] = {
            "id": pool_id,
            "provisioning_status": provisioning_status,
        }
        if operating_status is not None:
            entry["operating_status"] = operating_status
        payload: dict[str, list[dict[str, Any]]] = {"pools": [entry]}
        if listener_id:
            payload["listeners"] = [{"id": listener_id, "provisioning_status": lib_consts.ACTIVE}]
        if lb_id:
            payload["loadbalancers"] = [{"id": lb_id, "provisioning_status": lib_consts.ACTIVE}]
        return self.update_status(payload)

    def update_member_status(
        self,
        member_id: str,
        provisioning_status: str = lib_consts.ACTIVE,
        operating_status: Optional[str] = lib_consts.ONLINE,
        lb_id: Optional[str] = None,
        pool_id: Optional[str] = None,
        listener_id: Optional[str] = None,
    ) -> bool:
        """Update single member status and optionally parent pool, listener, and loadbalancer."""
        entry: dict[str, Any] = {
            "id": member_id,
            "provisioning_status": provisioning_status,
        }
        if operating_status is not None:
            entry["operating_status"] = operating_status
        payload: dict[str, list[dict[str, Any]]] = {"members": [entry]}
        if pool_id:
            payload["pools"] = [{"id": pool_id, "provisioning_status": lib_consts.ACTIVE}]
        if listener_id:
            payload["listeners"] = [{"id": listener_id, "provisioning_status": lib_consts.ACTIVE}]
        if lb_id:
            payload["loadbalancers"] = [{"id": lb_id, "provisioning_status": lib_consts.ACTIVE}]
        return self.update_status(payload)

    def update_healthmonitor_status(
        self,
        hm_id: str,
        provisioning_status: str = lib_consts.ACTIVE,
        operating_status: Optional[str] = lib_consts.ONLINE,
        lb_id: Optional[str] = None,
        pool_id: Optional[str] = None,
        listener_id: Optional[str] = None,
    ) -> bool:
        """Update single health monitor status and optionally parent pool, listener, and loadbalancer."""
        entry: dict[str, Any] = {
            "id": hm_id,
            "provisioning_status": provisioning_status,
        }
        if operating_status is not None:
            entry["operating_status"] = operating_status
        payload: dict[str, list[dict[str, Any]]] = {"healthmonitors": [entry]}
        if pool_id:
            payload["pools"] = [{"id": pool_id, "provisioning_status": lib_consts.ACTIVE}]
        if listener_id:
            payload["listeners"] = [{"id": listener_id, "provisioning_status": lib_consts.ACTIVE}]
        if lb_id:
            payload["loadbalancers"] = [{"id": lb_id, "provisioning_status": lib_consts.ACTIVE}]
        return self.update_status(payload)

    # -------------------------------------------------------------------------
    # Statistics Synchronization Methods
    # -------------------------------------------------------------------------

    def update_listener_statistics(self, statistics: dict[str, list[dict[str, Any]]]) -> bool:
        """Send listener statistics dictionary to Octavia via the stats socket.

        Args:
            statistics: Dict of format {"listeners": [{"id": ..., "bytes_in": ..., ...}]}

        Returns:
            bool: True if stats were transmitted successfully, False otherwise.
        """
        LOG.debug("Sending listener statistics update to Octavia: %s", statistics)
        lib = self.driver_lib
        if lib is None:
            LOG.debug("DriverLibrary stats socket unavailable; stats update skipped")
            return False

        try:
            lib.update_listener_statistics(statistics)
            return True
        except driver_exceptions.UpdateStatisticsError as e:
            LOG.warning("Octavia rejected statistics update: %s", e)
            return False
        except Exception as e:
            LOG.debug("Stats socket transmission failed: %s", e)
            return False

    def sync_listener_statistics(
        self,
        listener_id: str,
        client: Optional[Any] = None,
        external_ip: Optional[str] = None,
        port: Optional[int] = None,
        protocol: str = "tcp",
    ) -> bool:
        """Synchronize statistics for a single listener from LoxiLB into Octavia."""
        if client is None:
            from octavia_loxilb.client.client import LoxiLBClient
            client = LoxiLBClient(config=self.config)

        if external_ip is None or port is None:
            if self.driver_lib:
                try:
                    listener_obj = self.driver_lib.get_listener(listener_id)
                    port = getattr(listener_obj, "protocol_port", None)
                    raw_proto = getattr(listener_obj, "protocol", "TCP")
                    protocol = str(raw_proto).lower()
                    lb = getattr(listener_obj, "loadbalancer", None)
                    if lb:
                        external_ip = getattr(lb, "vip_address", None)
                except Exception as e:
                    LOG.debug("Could not resolve listener %s for stats sync: %s", listener_id, e)

        if not external_ip or port is None:
            LOG.debug("Insufficient VIP info to sync stats for listener %s", listener_id)
            return False

        stats = client.get_loadbalancer_stats(external_ip, port, protocol)
        payload = {
            "listeners": [
                {
                    "id": listener_id,
                    "bytes_in": stats.get("bytes_in", 0),
                    "bytes_out": stats.get("bytes_out", 0),
                    "active_connections": stats.get("active_connections", 0),
                    "total_connections": stats.get("total_connections", 0),
                    "request_errors": stats.get("request_errors", 0),
                }
            ]
        }
        return self.update_listener_statistics(payload)

    def sync_all_statistics(self, client: Optional[Any] = None) -> int:
        """Fetch all LoxiLB loadbalancer statistics and push to Octavia."""
        if client is None:
            from octavia_loxilb.client.client import LoxiLBClient
            client = LoxiLBClient(config=self.config)

        all_stats = client.get_all_loadbalancer_stats()
        if not all_stats:
            return 0

        listener_records = []
        for stat in all_stats:
            name = stat.get("name", "")
            listener_id = None
            # Service name format is octavia-<lb_id>-<listener_id>
            if name.startswith("octavia-"):
                uuids = re.findall(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", name)
                if len(uuids) >= 2:
                    listener_id = uuids[1]
                elif len(uuids) == 1:
                    listener_id = uuids[0]
                else:
                    parts = name.split("-", 2)
                    if len(parts) >= 3:
                        listener_id = parts[2]
                    elif len(parts) == 2:
                        listener_id = parts[1]

            if not listener_id:
                continue

            listener_records.append(
                {
                    "id": listener_id,
                    "bytes_in": stat.get("bytes_in", 0),
                    "bytes_out": stat.get("bytes_out", 0),
                    "active_connections": stat.get("active_connections", 0),
                    "total_connections": stat.get("total_connections", 0),
                    "request_errors": stat.get("request_errors", 0),
                }
            )

        if listener_records:
            success = self.update_listener_statistics({"listeners": listener_records})
            return len(listener_records) if success else 0
        return 0


class StatsCollector:
    """Background periodic thread to synchronize LoxiLB statistics to Octavia."""

    def __init__(
        self,
        status_syncer: StatusSynchronizer,
        client: Optional[Any] = None,
        interval: int = 5,
    ):
        self.status_syncer = status_syncer
        self.client = client
        self.interval = interval
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the background statistics synchronization thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="LoxiLBStatsCollector")
        self._thread.daemon = True
        self._thread.start()
        LOG.info("Started LoxiLB StatsCollector thread (interval=%ds)", self.interval)

    def stop(self) -> None:
        """Stop the background statistics synchronization thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        LOG.info("Stopped LoxiLB StatsCollector thread")

    def _run(self) -> None:
        """Worker loop for periodic statistics synchronization."""
        while not self._stop_event.is_set():
            try:
                self.status_syncer.sync_all_statistics(client=self.client)
            except Exception as e:
                LOG.debug("Error during periodic stats synchronization: %s", e)
            self._stop_event.wait(timeout=self.interval)

