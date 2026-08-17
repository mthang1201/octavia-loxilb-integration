"""Translator between Octavia data models and LoxiLB service models."""

from typing import Any, Optional

import octavia_lib.api.drivers.exceptions as driver_exceptions
from octavia_lib.common import constants as lib_consts
from oslo_log import log as logging

from octavia_loxilb.client.models import Endpoint, LoadbalanceEntry, ServiceArguments
from octavia_loxilb.common import constants, exceptions

LOG = logging.getLogger(__name__)


def _get_field(obj: Any, key: str, default: Any = None) -> Any:
    """Helper to extract a field from either an Octavia DataModel or dict."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        val = obj.get(key, default)
    else:
        val = getattr(obj, key, default)

    # In octavia-lib data models, unset attributes are represented by octavia_lib.api.drivers.data_models.Unset
    if val.__class__.__name__ == "Unset":
        return default
    return val


def generate_service_name(loadbalancer: Any, listener: Any) -> str:
    """Generate a deterministic service name for a LoxiLB loadbalancer rule."""
    lb_id = _get_field(loadbalancer, "loadbalancer_id") or _get_field(loadbalancer, "id") or "unknown_lb"
    listener_id = _get_field(listener, "listener_id") or _get_field(listener, "id")
    if listener_id:
        return f"octavia-{lb_id}-{listener_id}"

    protocol = _get_field(listener, "protocol", "tcp").lower()
    port = _get_field(listener, "protocol_port", 0)
    return f"octavia-{lb_id}-{protocol}-{port}"


def get_vip_address(loadbalancer: Any) -> str:
    """Extract VIP address from loadbalancer object or dict."""
    vip_addr = _get_field(loadbalancer, "vip_address")
    if not vip_addr:
        vip_obj = _get_field(loadbalancer, "vip")
        if vip_obj:
            vip_addr = _get_field(vip_obj, "vip_address") or _get_field(vip_obj, "ip_address")

    if not vip_addr:
        raise exceptions.LoxiLBTranslationError(
            resource="LoadBalancer",
            reason="Missing required vip_address on LoadBalancer object",
        )
    return str(vip_addr)


def to_loxilb_endpoint(member: Any, operating_status: Optional[str] = None) -> Optional[Endpoint]:
    """Convert an Octavia Member into a LoxiLB Endpoint."""
    admin_state_up = _get_field(member, "admin_state_up", True)
    if admin_state_up is False:
        LOG.debug("Skipping member %s because admin_state_up is False", _get_field(member, "member_id"))
        return None

    address = _get_field(member, "address") or _get_field(member, "ip_address")
    protocol_port = _get_field(member, "protocol_port")
    weight = _get_field(member, "weight", 1)

    if not address or protocol_port is None:
        LOG.warning("Member %s is missing address or protocol_port", _get_field(member, "member_id"))
        return None

    # Determine state
    state = None
    if operating_status:
        if operating_status in [lib_consts.ONLINE, lib_consts.NO_MONITOR]:
            state = "active"
        elif operating_status in [lib_consts.OFFLINE, lib_consts.ERROR]:
            state = "inactive"

    return Endpoint(
        endpointIP=str(address),
        targetPort=int(protocol_port),
        weight=int(weight) if weight is not None else 1,
        state=state,
    )


def to_loxilb_service(
    loadbalancer: Any,
    listener: Any,
    pool: Optional[Any] = None,
    members: Optional[list[Any]] = None,
    healthmonitor: Optional[Any] = None,
    nat_mode: int = constants.NAT_MODE_ONEARM,
    bgp_enabled: bool = False,
    snat_enabled: bool = False,
) -> LoadbalanceEntry:
    """Translate Octavia resources into a LoxiLB LoadbalanceEntry."""
    if not loadbalancer:
        raise exceptions.LoxiLBTranslationError("LoadBalancer", "LoadBalancer cannot be None")
    if not listener:
        raise exceptions.LoxiLBTranslationError("Listener", "Listener cannot be None")

    vip = get_vip_address(loadbalancer)
    port = _get_field(listener, "protocol_port")
    if port is None:
        raise exceptions.LoxiLBTranslationError("Listener", "Missing protocol_port on Listener")

    raw_protocol = _get_field(listener, "protocol", lib_consts.PROTOCOL_TCP)
    protocol_upper = str(raw_protocol).upper()

    # Reject unsupported listener protocols (L7, TLS termination)
    if protocol_upper not in constants.SUPPORTED_PROTOCOLS:
        raise driver_exceptions.UnsupportedOptionError(
            user_fault_string=f"Protocol '{protocol_upper}' is not supported by LoxiLB provider driver. "
            f"Supported protocols: {constants.SUPPORTED_PROTOCOLS}",
            operator_fault_string=f"Protocol {protocol_upper} not supported",
        )

    loxilb_protocol = constants.PROTOCOL_MAP[protocol_upper]

    # Resolve Pool (from explicit argument or listener.default_pool)
    if pool is None:
        pool = _get_field(listener, "default_pool")

    # Algorithm selection
    sel = constants.LOXILB_SEL_ROUND_ROBIN
    if pool is not None:
        algo = _get_field(pool, "lb_algorithm", lib_consts.LB_ALGORITHM_ROUND_ROBIN)
        if algo not in constants.LB_ALGORITHM_MAP:
            raise driver_exceptions.UnsupportedOptionError(
                user_fault_string=f"Load balancing algorithm '{algo}' is not supported by LoxiLB provider driver. "
                f"Supported algorithms: {list(constants.LB_ALGORITHM_MAP.keys())}",
                operator_fault_string=f"Algorithm {algo} not supported",
            )
        sel = constants.LB_ALGORITHM_MAP[algo]

        # Check session persistence
        sp = _get_field(pool, "session_persistence")
        if sp is not None:
            sp_type = _get_field(sp, "type")
            if sp_type == lib_consts.SESSION_PERSISTENCE_SOURCE_IP:
                sel = constants.LOXILB_SEL_PERSIST
            elif sp_type in [lib_consts.SESSION_PERSISTENCE_HTTP_COOKIE, lib_consts.SESSION_PERSISTENCE_APP_COOKIE]:
                raise driver_exceptions.UnsupportedOptionError(
                    user_fault_string=f"Cookie session persistence '{sp_type}' is not supported by L4 LoxiLB driver.",
                    operator_fault_string=f"Unsupported persistence type {sp_type}",
                )

    service_name = generate_service_name(loadbalancer, listener)

    # Health Monitor configuration
    if healthmonitor is None and pool is not None:
        healthmonitor = _get_field(pool, "healthmonitor")

    monitor_enabled = False
    probetype: Optional[str] = None
    probeport: Optional[int] = None
    probereq: Optional[str] = None
    proberesp: Optional[str] = None
    probe_timeout: Optional[int] = None
    probe_retries: Optional[int] = None

    if healthmonitor is not None:
        hm_admin_up = _get_field(healthmonitor, "admin_state_up", True)
        if hm_admin_up is not False:
            hm_type = str(_get_field(healthmonitor, "type", "")).upper()
            if hm_type not in constants.SUPPORTED_HEALTH_MONITOR_TYPES:
                raise driver_exceptions.UnsupportedOptionError(
                    user_fault_string=f"Health monitor type '{hm_type}' is not supported by LoxiLB provider driver. "
                    f"Supported types: {constants.SUPPORTED_HEALTH_MONITOR_TYPES}",
                    operator_fault_string=f"Health monitor type {hm_type} not supported",
                )

            monitor_enabled = True
            probetype = constants.HEALTH_MONITOR_PROBE_MAP[hm_type]
            probe_timeout = _get_field(healthmonitor, "timeout")
            probe_retries = _get_field(healthmonitor, "max_retries_down") or _get_field(healthmonitor, "max_retries")

            # HTTP / HTTPS probe specifics
            if hm_type in [lib_consts.HEALTH_MONITOR_HTTP, lib_consts.HEALTH_MONITOR_HTTPS]:
                url_path = _get_field(healthmonitor, "url_path", "/")
                http_method = _get_field(healthmonitor, "http_method", "GET")
                domain = _get_field(healthmonitor, "domain_name", "localhost")
                probereq = f"{http_method} {url_path} HTTP/1.1\r\nHost: {domain}\r\n\r\n"
                expected_codes = _get_field(healthmonitor, "expected_codes", "200")
                proberesp = f"HTTP/1.1 {expected_codes.split(',')[0].strip()}"

    service_args = ServiceArguments(
        externalIP=vip,
        port=int(port),
        protocol=loxilb_protocol,
        sel=sel,
        mode=nat_mode,
        monitor=monitor_enabled,
        name=service_name,
        probetype=probetype,
        probeport=probeport,
        probereq=probereq,
        proberesp=proberesp,
        probeTimeout=int(probe_timeout) if probe_timeout is not None else None,
        probeRetries=int(probe_retries) if probe_retries is not None else None,
        bgp=bgp_enabled if bgp_enabled else None,
        snat=snat_enabled if snat_enabled else None,
    )

    # Endpoints resolution
    endpoint_list: list[Endpoint] = []
    member_pool = members
    if member_pool is None and pool is not None:
        member_pool = _get_field(pool, "members", [])

    if member_pool:
        for m in member_pool:
            ep = to_loxilb_endpoint(m)
            if ep is not None:
                endpoint_list.append(ep)

    return LoadbalanceEntry(
        serviceArguments=service_args,
        endpoints=endpoint_list,
    )
