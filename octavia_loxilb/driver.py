"""LoxiLB Octavia Provider Driver."""

from typing import Any, Optional

from octavia_lib.api.drivers import driver_lib
from octavia_lib.api.drivers import exceptions as driver_exceptions
from octavia_lib.api.drivers import provider_base
from octavia_lib.common import constants as lib_consts
from oslo_config import cfg
from oslo_log import log as logging

from octavia_loxilb.client.client import LoxiLBClient
from octavia_loxilb.common import config, constants, exceptions
from octavia_loxilb.status.synchronizer import StatsCollector, StatusSynchronizer
from octavia_loxilb.translation.translator import (
    _get_field,
    generate_service_name,
    get_vip_address,
    to_loxilb_service,
)

LOG = logging.getLogger(__name__)


class LoxiLBProviderDriver(provider_base.ProviderDriver):
    """LoxiLB Provider Driver for OpenStack Octavia."""

    def __init__(
        self,
        client: Optional[LoxiLBClient] = None,
        status_syncer: Optional[StatusSynchronizer] = None,
        driver_lib_instance: Optional[Any] = None,
    ):
        """Initialize the LoxiLB provider driver."""
        super().__init__()
        # Register and configure oslo.config
        try:
            config.register_opts(cfg.CONF)
        except cfg.DuplicateOptError:
            pass

        self.config = getattr(cfg.CONF, "loxilb", None)
        self.client = client or LoxiLBClient(config=self.config)
        self._driver_lib = driver_lib_instance
        self.status_syncer = status_syncer or StatusSynchronizer(
            config=self.config, driver_lib_instance=driver_lib_instance
        )

        # Initialize background statistics collector
        self.stats_collector: Optional[StatsCollector] = None
        stats_enabled = getattr(self.config, "stats_enabled", True)
        stats_interval = getattr(self.config, "stats_interval", 5)
        if stats_enabled:
            self.stats_collector = StatsCollector(
                status_syncer=self.status_syncer,
                client=self.client,
                interval=stats_interval,
            )
            if self.status_syncer.driver_lib is not None:
                self.stats_collector.start()

        LOG.info("LoxiLBProviderDriver initialized successfully (version: %s)", constants.DRIVER_VERSION)

    @property
    def driver_lib(self) -> Optional[Any]:
        """Lazily retrieve driver_lib instance."""
        if self._driver_lib is None:
            self._driver_lib = self.status_syncer.driver_lib
        return self._driver_lib

    # -------------------------------------------------------------------------
    # Helper Resolution Methods
    # -------------------------------------------------------------------------

    def _resolve_loadbalancer(self, resource: Any) -> Optional[Any]:
        """Resolve parent loadbalancer from a resource or via DriverLibrary."""
        lb = _get_field(resource, "loadbalancer")
        if lb:
            return lb
        lb_id = _get_field(resource, "loadbalancer_id")
        if lb_id and self.driver_lib:
            try:
                return self.driver_lib.get_loadbalancer(lb_id)
            except Exception as e:
                LOG.debug("Could not resolve loadbalancer %s from driver_lib: %s", lb_id, e)
        return None

    def _resolve_listener(self, resource: Any) -> Optional[Any]:
        """Resolve parent listener from a pool or via DriverLibrary."""
        listener = _get_field(resource, "listener")
        if listener:
            return listener
        listener_id = _get_field(resource, "listener_id")
        if listener_id and self.driver_lib:
            try:
                return self.driver_lib.get_listener(listener_id)
            except Exception as e:
                LOG.debug("Could not resolve listener %s from driver_lib: %s", listener_id, e)
        return None

    def _reconcile_service(
        self,
        loadbalancer: Any,
        listener: Any,
        pool: Optional[Any] = None,
        members: Optional[list[Any]] = None,
        healthmonitor: Optional[Any] = None,
    ) -> None:
        """Translate Octavia resources and apply the service rule to LoxiLB."""
        nat_mode_name = getattr(self.config, "default_nat_mode", "onearm")
        nat_mode = constants.NAT_MODE_MAP.get(nat_mode_name, constants.NAT_MODE_ONEARM)
        bgp_enabled = getattr(self.config, "bgp_enabled", False)
        snat_enabled = getattr(self.config, "snat_enabled", False)

        entry = to_loxilb_service(
            loadbalancer=loadbalancer,
            listener=listener,
            pool=pool,
            members=members,
            healthmonitor=healthmonitor,
            nat_mode=nat_mode,
            bgp_enabled=bgp_enabled,
            snat_enabled=snat_enabled,
        )
        if entry.endpoints:
            self.client.create_loadbalancer(entry)
        else:
            # LoxiLB requires >=1 endpoint to activate dataplane rule; if empty, clean up any existing rule
            ext_ip = entry.serviceArguments.externalIP
            port = entry.serviceArguments.port
            proto = entry.serviceArguments.protocol
            if ext_ip and port and proto:
                self.client.delete_loadbalancer(ext_ip, port, proto)

    # -------------------------------------------------------------------------
    # LoadBalancer Operations
    # -------------------------------------------------------------------------

    def loadbalancer_create(self, loadbalancer: Any) -> None:
        """Create a load balancer."""
        lb_id = _get_field(loadbalancer, "loadbalancer_id") or _get_field(loadbalancer, "id")
        LOG.info("Creating loadbalancer: %s", lb_id)
        # For L4 model, top-level LB is a logical envelope; if listeners exist, reconcile them
        listeners = _get_field(loadbalancer, "listeners", [])
        if listeners:
            for listener in listeners:
                try:
                    self._reconcile_service(loadbalancer, listener)
                except Exception as e:
                    LOG.error("Failed to configure listener %s on LB create: %s", _get_field(listener, "listener_id"), e)
                    self.status_syncer.update_loadbalancer_status(lb_id, provisioning_status=lib_consts.ERROR)
                    raise

        self.status_syncer.update_loadbalancer_status(
            lb_id, provisioning_status=lib_consts.ACTIVE, operating_status=lib_consts.ONLINE
        )

    def loadbalancer_update(self, old_loadbalancer: Any, new_loadbalancer: Any) -> None:
        """Update a load balancer."""
        lb_id = _get_field(new_loadbalancer, "loadbalancer_id") or _get_field(new_loadbalancer, "id")
        LOG.info("Updating loadbalancer: %s", lb_id)
        listeners = _get_field(new_loadbalancer, "listeners", [])
        if listeners:
            for listener in listeners:
                self._reconcile_service(new_loadbalancer, listener)

        self.status_syncer.update_loadbalancer_status(
            lb_id, provisioning_status=lib_consts.ACTIVE
        )

    def loadbalancer_delete(self, loadbalancer: Any, cascade: bool = False) -> None:
        """Delete a load balancer."""
        lb_id = _get_field(loadbalancer, "loadbalancer_id") or _get_field(loadbalancer, "id")
        LOG.info("Deleting loadbalancer: %s (cascade=%s)", lb_id, cascade)
        listeners = _get_field(loadbalancer, "listeners", [])
        if listeners:
            for listener in listeners:
                self.listener_delete(listener)
        else:
            # Attempt deleting rules named with this LB ID
            self.client.delete_loadbalancer_by_name(f"octavia-{lb_id}")

        self.status_syncer.update_loadbalancer_status(
            lb_id, provisioning_status=lib_consts.DELETED
        )

    def loadbalancer_failover(self, loadbalancer_id: str) -> None:
        """Failover a load balancer."""
        LOG.info("Failing over loadbalancer: %s", loadbalancer_id)
        self.status_syncer.update_loadbalancer_status(
            loadbalancer_id, provisioning_status=lib_consts.ACTIVE, operating_status=lib_consts.ONLINE
        )

    # -------------------------------------------------------------------------
    # Listener Operations
    # -------------------------------------------------------------------------

    def listener_create(self, listener: Any) -> None:
        """Create a listener."""
        listener_id = _get_field(listener, "listener_id") or _get_field(listener, "id")
        LOG.info("Creating listener: %s", listener_id)
        lb = self._resolve_loadbalancer(listener)
        if lb is None:
            LOG.warning("Could not resolve loadbalancer for listener %s; creating deferred rule", listener_id)
        else:
            self._reconcile_service(loadbalancer=lb, listener=listener)

        lb_id = _get_field(lb, "loadbalancer_id") or _get_field(lb, "id") if lb else None
        self.status_syncer.update_listener_status(
            listener_id, provisioning_status=lib_consts.ACTIVE, operating_status=lib_consts.ONLINE, lb_id=lb_id
        )

    def listener_update(self, old_listener: Any, new_listener: Any) -> None:
        """Update a listener."""
        listener_id = _get_field(new_listener, "listener_id") or _get_field(new_listener, "id")
        LOG.info("Updating listener: %s", listener_id)
        lb = self._resolve_loadbalancer(new_listener)
        if lb is not None:
            self._reconcile_service(loadbalancer=lb, listener=new_listener)

        lb_id = _get_field(lb, "loadbalancer_id") or _get_field(lb, "id") if lb else None
        self.status_syncer.update_listener_status(
            listener_id, provisioning_status=lib_consts.ACTIVE, lb_id=lb_id
        )

    def listener_delete(self, listener: Any) -> None:
        """Delete a listener."""
        listener_id = _get_field(listener, "listener_id") or _get_field(listener, "id")
        LOG.info("Deleting listener: %s", listener_id)
        lb = self._resolve_loadbalancer(listener)
        if lb is not None:
            vip = get_vip_address(lb)
            port = _get_field(listener, "protocol_port")
            raw_proto = _get_field(listener, "protocol", "TCP").upper()
            proto = constants.PROTOCOL_MAP.get(raw_proto, "tcp")
            self.client.delete_loadbalancer(external_ip=vip, port=int(port), protocol=proto)
        else:
            name = generate_service_name(lb, listener)
            self.client.delete_loadbalancer_by_name(name)

        lb_id = _get_field(lb, "loadbalancer_id") or _get_field(lb, "id") if lb else None
        self.status_syncer.update_listener_status(
            listener_id, provisioning_status=lib_consts.DELETED, lb_id=lb_id
        )

    # -------------------------------------------------------------------------
    # Pool Operations
    # -------------------------------------------------------------------------

    def pool_create(self, pool: Any) -> None:
        """Create a pool."""
        pool_id = _get_field(pool, "pool_id") or _get_field(pool, "id")
        LOG.info("Creating pool: %s", pool_id)
        lb = self._resolve_loadbalancer(pool)
        listener = self._resolve_listener(pool)
        if lb is not None and listener is not None:
            self._reconcile_service(loadbalancer=lb, listener=listener, pool=pool)

        lb_id = _get_field(lb, "loadbalancer_id") or _get_field(lb, "id") if lb else None
        listener_id = _get_field(listener, "listener_id") or _get_field(listener, "id") if listener else None
        self.status_syncer.update_pool_status(
            pool_id, provisioning_status=lib_consts.ACTIVE, operating_status=lib_consts.ONLINE, lb_id=lb_id, listener_id=listener_id
        )

    def pool_update(self, old_pool: Any, new_pool: Any) -> None:
        """Update a pool."""
        pool_id = _get_field(new_pool, "pool_id") or _get_field(new_pool, "id")
        LOG.info("Updating pool: %s", pool_id)
        lb = self._resolve_loadbalancer(new_pool)
        listener = self._resolve_listener(new_pool)
        if lb is not None and listener is not None:
            self._reconcile_service(loadbalancer=lb, listener=listener, pool=new_pool)

        lb_id = _get_field(lb, "loadbalancer_id") or _get_field(lb, "id") if lb else None
        listener_id = _get_field(listener, "listener_id") or _get_field(listener, "id") if listener else None
        self.status_syncer.update_pool_status(
            pool_id, provisioning_status=lib_consts.ACTIVE, lb_id=lb_id, listener_id=listener_id
        )

    def pool_delete(self, pool: Any) -> None:
        """Delete a pool."""
        pool_id = _get_field(pool, "pool_id") or _get_field(pool, "id")
        LOG.info("Deleting pool: %s", pool_id)
        lb = self._resolve_loadbalancer(pool)
        listener = self._resolve_listener(pool)
        if lb is not None and listener is not None:
            # Reconcile listener with empty pool
            self._reconcile_service(loadbalancer=lb, listener=listener, pool=None, members=[])

        lb_id = _get_field(lb, "loadbalancer_id") or _get_field(lb, "id") if lb else None
        listener_id = _get_field(listener, "listener_id") or _get_field(listener, "id") if listener else None
        self.status_syncer.update_pool_status(
            pool_id, provisioning_status=lib_consts.DELETED, lb_id=lb_id, listener_id=listener_id
        )

    # -------------------------------------------------------------------------
    # Member Operations
    # -------------------------------------------------------------------------

    def member_create(self, member: Any) -> None:
        """Create a member in a pool."""
        member_id = _get_field(member, "member_id") or _get_field(member, "id")
        LOG.info("Creating member: %s", member_id)
        pool_id = _get_field(member, "pool_id")
        pool = None
        if pool_id and self.driver_lib:
            try:
                pool = self.driver_lib.get_pool(pool_id)
            except Exception as e:
                LOG.debug("Could not get pool %s: %s", pool_id, e)

        lb = None
        listener = None
        if pool is not None:
            lb = self._resolve_loadbalancer(pool)
            listener = self._resolve_listener(pool)
            if lb is not None and listener is not None:
                members = _get_field(pool, "members", [])
                if member not in members:
                    members = list(members) + [member]
                self._reconcile_service(loadbalancer=lb, listener=listener, pool=pool, members=members)

        lb_id = _get_field(lb, "loadbalancer_id") or _get_field(lb, "id") if lb else None
        listener_id = _get_field(listener, "listener_id") or _get_field(listener, "id") if listener else None
        self.status_syncer.update_member_status(
            member_id, provisioning_status=lib_consts.ACTIVE, operating_status=lib_consts.ONLINE, lb_id=lb_id, pool_id=pool_id, listener_id=listener_id
        )

    def member_update(self, old_member: Any, new_member: Any) -> None:
        """Update a member."""
        member_id = _get_field(new_member, "member_id") or _get_field(new_member, "id")
        LOG.info("Updating member: %s", member_id)
        pool_id = _get_field(new_member, "pool_id")
        pool = None
        if pool_id and self.driver_lib:
            try:
                pool = self.driver_lib.get_pool(pool_id)
            except Exception as e:
                LOG.debug("Could not get pool %s: %s", pool_id, e)

        lb = None
        listener = None
        if pool is not None:
            lb = self._resolve_loadbalancer(pool)
            listener = self._resolve_listener(pool)
            if lb is not None and listener is not None:
                self._reconcile_service(loadbalancer=lb, listener=listener, pool=pool)

        lb_id = _get_field(lb, "loadbalancer_id") or _get_field(lb, "id") if lb else None
        listener_id = _get_field(listener, "listener_id") or _get_field(listener, "id") if listener else None
        self.status_syncer.update_member_status(
            member_id, provisioning_status=lib_consts.ACTIVE, lb_id=lb_id, pool_id=pool_id, listener_id=listener_id
        )

    def member_delete(self, member: Any) -> None:
        """Delete a member."""
        member_id = _get_field(member, "member_id") or _get_field(member, "id")
        LOG.info("Deleting member: %s", member_id)
        pool_id = _get_field(member, "pool_id")
        pool = None
        if pool_id and self.driver_lib:
            try:
                pool = self.driver_lib.get_pool(pool_id)
            except Exception as e:
                LOG.debug("Could not get pool %s: %s", pool_id, e)

        lb = None
        listener = None
        if pool is not None:
            lb = self._resolve_loadbalancer(pool)
            listener = self._resolve_listener(pool)
            if lb is not None and listener is not None:
                members = [m for m in _get_field(pool, "members", []) if (_get_field(m, "member_id") or _get_field(m, "id")) != member_id]
                self._reconcile_service(loadbalancer=lb, listener=listener, pool=pool, members=members)

        lb_id = _get_field(lb, "loadbalancer_id") or _get_field(lb, "id") if lb else None
        listener_id = _get_field(listener, "listener_id") or _get_field(listener, "id") if listener else None
        self.status_syncer.update_member_status(
            member_id, provisioning_status=lib_consts.DELETED, lb_id=lb_id, pool_id=pool_id, listener_id=listener_id
        )

    def member_batch_update(self, pool_id: str, members: list[Any]) -> None:
        """Batch update members for a pool."""
        LOG.info("Batch updating %d members for pool: %s", len(members), pool_id)
        pool = None
        if pool_id and self.driver_lib:
            try:
                pool = self.driver_lib.get_pool(pool_id)
            except Exception as e:
                LOG.debug("Could not get pool %s: %s", pool_id, e)

        lb = None
        listener = None
        if pool is not None:
            lb = self._resolve_loadbalancer(pool)
            listener = self._resolve_listener(pool)
            if lb is not None and listener is not None:
                self._reconcile_service(loadbalancer=lb, listener=listener, pool=pool, members=members)

        lb_id = _get_field(lb, "loadbalancer_id") or _get_field(lb, "id") if lb else None
        listener_id = _get_field(listener, "listener_id") or _get_field(listener, "id") if listener else None
        payload_members = [
            {"id": _get_field(m, "member_id") or _get_field(m, "id"),
             "provisioning_status": lib_consts.ACTIVE,
             "operating_status": lib_consts.ONLINE}
            for m in members if (_get_field(m, "member_id") or _get_field(m, "id"))
        ]
        status_dict: dict[str, list[dict[str, Any]]] = {"members": payload_members}
        if pool_id:
            status_dict["pools"] = [{"id": pool_id, "provisioning_status": lib_consts.ACTIVE}]
        if listener_id:
            status_dict["listeners"] = [{"id": listener_id, "provisioning_status": lib_consts.ACTIVE}]
        if lb_id:
            status_dict["loadbalancers"] = [{"id": lb_id, "provisioning_status": lib_consts.ACTIVE}]
        self.status_syncer.update_status(status_dict)

    # -------------------------------------------------------------------------
    # HealthMonitor Operations
    # -------------------------------------------------------------------------

    def health_monitor_create(self, healthmonitor: Any) -> None:
        """Create a health monitor."""
        hm_id = _get_field(healthmonitor, "healthmonitor_id") or _get_field(healthmonitor, "id")
        LOG.info("Creating health monitor: %s", hm_id)
        pool_id = _get_field(healthmonitor, "pool_id")
        pool = None
        if pool_id and self.driver_lib:
            try:
                pool = self.driver_lib.get_pool(pool_id)
            except Exception as e:
                LOG.debug("Could not get pool %s: %s", pool_id, e)

        lb = None
        listener = None
        if pool is not None:
            lb = self._resolve_loadbalancer(pool)
            listener = self._resolve_listener(pool)
            if lb is not None and listener is not None:
                self._reconcile_service(
                    loadbalancer=lb, listener=listener, pool=pool, healthmonitor=healthmonitor
                )

        lb_id = _get_field(lb, "loadbalancer_id") or _get_field(lb, "id") if lb else None
        listener_id = _get_field(listener, "listener_id") or _get_field(listener, "id") if listener else None
        self.status_syncer.update_healthmonitor_status(
            hm_id, provisioning_status=lib_consts.ACTIVE, operating_status=lib_consts.ONLINE, lb_id=lb_id, pool_id=pool_id, listener_id=listener_id
        )

    def health_monitor_update(self, old_healthmonitor: Any, new_healthmonitor: Any) -> None:
        """Update a health monitor."""
        hm_id = _get_field(new_healthmonitor, "healthmonitor_id") or _get_field(new_healthmonitor, "id")
        LOG.info("Updating health monitor: %s", hm_id)
        pool_id = _get_field(new_healthmonitor, "pool_id")
        pool = None
        if pool_id and self.driver_lib:
            try:
                pool = self.driver_lib.get_pool(pool_id)
            except Exception as e:
                LOG.debug("Could not get pool %s: %s", pool_id, e)

        lb = None
        listener = None
        if pool is not None:
            lb = self._resolve_loadbalancer(pool)
            listener = self._resolve_listener(pool)
            if lb is not None and listener is not None:
                self._reconcile_service(
                    loadbalancer=lb, listener=listener, pool=pool, healthmonitor=new_healthmonitor
                )

        lb_id = _get_field(lb, "loadbalancer_id") or _get_field(lb, "id") if lb else None
        listener_id = _get_field(listener, "listener_id") or _get_field(listener, "id") if listener else None
        self.status_syncer.update_healthmonitor_status(
            hm_id, provisioning_status=lib_consts.ACTIVE, lb_id=lb_id, pool_id=pool_id, listener_id=listener_id
        )

    def health_monitor_delete(self, healthmonitor: Any) -> None:
        """Delete a health monitor."""
        hm_id = _get_field(healthmonitor, "healthmonitor_id") or _get_field(healthmonitor, "id")
        LOG.info("Deleting health monitor: %s", hm_id)
        pool_id = _get_field(healthmonitor, "pool_id")
        pool = None
        if pool_id and self.driver_lib:
            try:
                pool = self.driver_lib.get_pool(pool_id)
            except Exception as e:
                LOG.debug("Could not get pool %s: %s", pool_id, e)

        lb = None
        listener = None
        if pool is not None:
            lb = self._resolve_loadbalancer(pool)
            listener = self._resolve_listener(pool)
            if lb is not None and listener is not None:
                self._reconcile_service(
                    loadbalancer=lb, listener=listener, pool=pool, healthmonitor=None
                )

        lb_id = _get_field(lb, "loadbalancer_id") or _get_field(lb, "id") if lb else None
        listener_id = _get_field(listener, "listener_id") or _get_field(listener, "id") if listener else None
        self.status_syncer.update_healthmonitor_status(
            hm_id, provisioning_status=lib_consts.DELETED, lb_id=lb_id, pool_id=pool_id, listener_id=listener_id
        )

    # -------------------------------------------------------------------------
    # Unsupported L7 Policies & Rules (Explicitly Rejected)
    # -------------------------------------------------------------------------

    def l7policy_create(self, l7policy: Any) -> None:
        raise driver_exceptions.NotImplementedError(
            user_fault_string="L7Policy is not supported by LoxiLB provider driver.",
            operator_fault_string="L7Policy not implemented",
        )

    def l7policy_update(self, old_l7policy: Any, new_l7policy: Any) -> None:
        raise driver_exceptions.NotImplementedError(
            user_fault_string="L7Policy is not supported by LoxiLB provider driver.",
            operator_fault_string="L7Policy not implemented",
        )

    def l7policy_delete(self, l7policy: Any) -> None:
        raise driver_exceptions.NotImplementedError(
            user_fault_string="L7Policy is not supported by LoxiLB provider driver.",
            operator_fault_string="L7Policy not implemented",
        )

    def l7rule_create(self, l7rule: Any) -> None:
        raise driver_exceptions.NotImplementedError(
            user_fault_string="L7Rule is not supported by LoxiLB provider driver.",
            operator_fault_string="L7Rule not implemented",
        )

    def l7rule_update(self, old_l7rule: Any, new_l7rule: Any) -> None:
        raise driver_exceptions.NotImplementedError(
            user_fault_string="L7Rule is not supported by LoxiLB provider driver.",
            operator_fault_string="L7Rule not implemented",
        )

    def l7rule_delete(self, l7rule: Any) -> None:
        raise driver_exceptions.NotImplementedError(
            user_fault_string="L7Rule is not supported by LoxiLB provider driver.",
            operator_fault_string="L7Rule not implemented",
        )

    # -------------------------------------------------------------------------
    # Metadata & VIP Validation
    # -------------------------------------------------------------------------

    def create_vip_port(
        self,
        loadbalancer_id: str,
        project_id: str,
        vip_dictionary: dict[str, Any],
        additional_vip_dicts: Optional[list[dict[str, Any]]] = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Let Octavia/Neutron own VIP port creation."""
        raise driver_exceptions.NotImplementedError(
            user_fault_string="VIP port creation is managed by Octavia.",
            operator_fault_string="create_vip_port not implemented by LoxiLB driver",
        )

    def validate_flavor(self, flavor_metadata: dict[str, Any]) -> bool:
        """Validate flavor metadata."""
        return True

    def validate_availability_zone(self, availability_zone_metadata: dict[str, Any]) -> bool:
        """Validate availability zone metadata."""
        return True
