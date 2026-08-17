"""Constants for Octavia LoxiLB Provider Driver."""

from octavia_lib.common import constants as lib_consts

# Driver identification
PROVIDER_NAME = "loxilb"
PROVIDER_DESCRIPTION = "LoxiLB Octavia Provider Driver"
DRIVER_VERSION = "0.1.0"

# LoxiLB default settings
DEFAULT_API_PORT = 11111
DEFAULT_API_TIMEOUT = 30
DEFAULT_API_RETRIES = 3
DEFAULT_API_RETRY_INTERVAL = 2

# LoxiLB REST API paths
API_PATH_STATUS = "/netlox/v1/version"
API_PATH_LOADBALANCER = "/netlox/v1/config/loadbalancer"
API_PATH_LOADBALANCER_ALL = "/netlox/v1/config/loadbalancer/all"
API_PATH_ENDPOINT = "/netlox/v1/config/endpoint"
API_PATH_ENDPOINT_ALL = "/netlox/v1/config/endpoint/all"
API_PATH_ENDPOINT_HOST_STATE = "/netlox/v1/config/endpointhoststate"

# Authentication types
AUTH_TYPE_NONE = "none"
AUTH_TYPE_BASIC = "password"
AUTH_TYPE_TOKEN = "token"
AUTH_TYPE_TLS = "tls"

# LoxiLB Selection Algorithms (from LoxiLB swagger / netlox spec)
LOXILB_SEL_ROUND_ROBIN = 0
LOXILB_SEL_HASH = 1
LOXILB_SEL_PRIORITY = 2
LOXILB_SEL_PERSIST = 3
LOXILB_SEL_LEAST_CONNECTIONS = 4

# Octavia Algorithm -> LoxiLB Selection Map
LB_ALGORITHM_MAP = {
    lib_consts.LB_ALGORITHM_ROUND_ROBIN: LOXILB_SEL_ROUND_ROBIN,
    lib_consts.LB_ALGORITHM_LEAST_CONNECTIONS: LOXILB_SEL_LEAST_CONNECTIONS,
    lib_consts.LB_ALGORITHM_SOURCE_IP: LOXILB_SEL_PERSIST,
}

# Supported Protocols
SUPPORTED_PROTOCOLS = [
    lib_consts.PROTOCOL_TCP,
    lib_consts.PROTOCOL_UDP,
    lib_consts.PROTOCOL_SCTP,
]

# Protocol mapping: Octavia -> LoxiLB
PROTOCOL_MAP = {
    lib_consts.PROTOCOL_TCP: "tcp",
    lib_consts.PROTOCOL_UDP: "udp",
    lib_consts.PROTOCOL_SCTP: "sctp",
}

# Health Monitor probe type mapping: Octavia -> LoxiLB
HEALTH_MONITOR_PROBE_MAP = {
    lib_consts.HEALTH_MONITOR_TCP: "tcp",
    lib_consts.HEALTH_MONITOR_HTTP: "http",
    lib_consts.HEALTH_MONITOR_HTTPS: "https",
    lib_consts.HEALTH_MONITOR_PING: "ping",
    lib_consts.HEALTH_MONITOR_UDP_CONNECT: "udp",
}

# Supported Health Monitor types
SUPPORTED_HEALTH_MONITOR_TYPES = list(HEALTH_MONITOR_PROBE_MAP.keys())

# LoxiLB NAT modes
NAT_MODE_DNAT = 0
NAT_MODE_ONEARM = 1
NAT_MODE_FULLNAT = 2
NAT_MODE_DSR = 3
NAT_MODE_FULLPROXY = 4
NAT_MODE_HOSTONEARM = 5

NAT_MODE_MAP = {
    "dnat": NAT_MODE_DNAT,
    "onearm": NAT_MODE_ONEARM,
    "fullnat": NAT_MODE_FULLNAT,
    "dsr": NAT_MODE_DSR,
    "fullproxy": NAT_MODE_FULLPROXY,
    "hostonearm": NAT_MODE_HOSTONEARM,
}
