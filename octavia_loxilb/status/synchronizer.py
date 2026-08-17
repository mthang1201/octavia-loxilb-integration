"""Status Synchronizer for Octavia LoxiLB Provider Driver."""

import os
from typing import Any, Optional

from octavia_lib.api.drivers import driver_lib
from octavia_lib.api.drivers import exceptions as driver_exceptions
from octavia_lib.common import constants as lib_consts
from oslo_config import cfg
from oslo_log import log as logging

LOG = logging.getLogger(__name__)


class StatusSynchronizer:
    """Synchronizes status from the LoxiLB driver back to Octavia via DriverLibrary."""

    def __init__(self, config: Optional[cfg.ConfigOpts] = None, driver_lib_instance: Optional[Any] = None):
        """Initialize the StatusSynchronizer."""
        self.config = config or cfg.CONF.loxilb
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

    def update_status(self, status: dict[str, list[dict[str, Any]]]) -> bool:
        """Send a status dictionary to Octavia via the status socket.

        Args:
            status: Formatted dictionary containing status updates for resources.

        Returns:
            bool: True if status updated successfully, False if socket error occurred.
        """
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
    ) -> bool:
        """Update single listener status."""
        entry: dict[str, Any] = {
            "id": listener_id,
            "provisioning_status": provisioning_status,
        }
        if operating_status is not None:
            entry["operating_status"] = operating_status
        return self.update_status({"listeners": [entry]})

    def update_pool_status(
        self,
        pool_id: str,
        provisioning_status: str = lib_consts.ACTIVE,
        operating_status: Optional[str] = lib_consts.ONLINE,
    ) -> bool:
        """Update single pool status."""
        entry: dict[str, Any] = {
            "id": pool_id,
            "provisioning_status": provisioning_status,
        }
        if operating_status is not None:
            entry["operating_status"] = operating_status
        return self.update_status({"pools": [entry]})

    def update_member_status(
        self,
        member_id: str,
        provisioning_status: str = lib_consts.ACTIVE,
        operating_status: Optional[str] = lib_consts.ONLINE,
    ) -> bool:
        """Update single member status."""
        entry: dict[str, Any] = {
            "id": member_id,
            "provisioning_status": provisioning_status,
        }
        if operating_status is not None:
            entry["operating_status"] = operating_status
        return self.update_status({"members": [entry]})

    def update_healthmonitor_status(
        self,
        hm_id: str,
        provisioning_status: str = lib_consts.ACTIVE,
        operating_status: Optional[str] = lib_consts.ONLINE,
    ) -> bool:
        """Update single health monitor status."""
        entry: dict[str, Any] = {
            "id": hm_id,
            "provisioning_status": provisioning_status,
        }
        if operating_status is not None:
            entry["operating_status"] = operating_status
        return self.update_status({"healthmonitors": [entry]})
