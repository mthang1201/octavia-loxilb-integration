"""Configuration options for Octavia LoxiLB Provider Driver."""

from oslo_config import cfg
from oslo_log import log as logging

from octavia_loxilb.common import constants

LOG = logging.getLogger(__name__)

LOXILB_GROUP = cfg.OptGroup(
    name="loxilb",
    title="LoxiLB Provider Driver Options",
    help="Configuration options for the LoxiLB Octavia Provider Driver.",
)

LOXILB_OPTS = [
    cfg.ListOpt(
        "api_endpoints",
        default=["http://127.0.0.1:11111"],
        help="List of LoxiLB API endpoint URLs (e.g. http://192.168.50.111:11111).",
    ),
    cfg.IntOpt(
        "api_timeout",
        default=constants.DEFAULT_API_TIMEOUT,
        help="Timeout in seconds for LoxiLB API requests.",
    ),
    cfg.IntOpt(
        "api_retries",
        default=constants.DEFAULT_API_RETRIES,
        help="Number of retries for failed LoxiLB API requests.",
    ),
    cfg.IntOpt(
        "api_retry_interval",
        default=constants.DEFAULT_API_RETRY_INTERVAL,
        help="Interval in seconds between retries.",
    ),
    cfg.StrOpt(
        "auth_type",
        default=constants.AUTH_TYPE_NONE,
        choices=[
            constants.AUTH_TYPE_NONE,
            constants.AUTH_TYPE_BASIC,
            constants.AUTH_TYPE_TOKEN,
            constants.AUTH_TYPE_TLS,
        ],
        help="Authentication method for LoxiLB API.",
    ),
    cfg.StrOpt(
        "username",
        default="",
        help="Username for basic authentication.",
    ),
    cfg.StrOpt(
        "password",
        default="",
        secret=True,
        help="Password for basic authentication.",
    ),
    cfg.StrOpt(
        "api_token",
        default="",
        secret=True,
        help="Bearer token for token-based authentication.",
    ),
    cfg.StrOpt(
        "tls_ca_cert_file",
        default="",
        help="Path to CA certificate bundle for TLS verification.",
    ),
    cfg.StrOpt(
        "tls_client_cert_file",
        default="",
        help="Path to client certificate file for mutual TLS.",
    ),
    cfg.StrOpt(
        "tls_client_key_file",
        default="",
        secret=True,
        help="Path to client private key file for mutual TLS.",
    ),
    cfg.BoolOpt(
        "tls_verify_cert",
        default=True,
        help="Whether to verify SSL/TLS certificates when communicating with LoxiLB.",
    ),
    cfg.StrOpt(
        "status_socket",
        default="/var/run/octavia/status.sock",
        help="Path to Octavia status socket for driver status reporting.",
    ),
    cfg.StrOpt(
        "stats_socket",
        default="/var/run/octavia/stats.sock",
        help="Path to Octavia statistics socket.",
    ),
    cfg.StrOpt(
        "get_socket",
        default="/var/run/octavia/get.sock",
        help="Path to Octavia get socket for reading object state.",
    ),
    cfg.StrOpt(
        "default_nat_mode",
        default="onearm",
        choices=["dnat", "onearm", "fullnat", "dsr", "fullproxy", "hostonearm"],
        help="Default NAT mode for LoxiLB service rules.",
    ),
    cfg.BoolOpt(
        "bgp_enabled",
        default=False,
        help="Whether BGP route advertisement is enabled in LoxiLB.",
    ),
    cfg.BoolOpt(
        "snat_enabled",
        default=False,
        help="Whether SNAT is enabled for service rules in LoxiLB.",
    ),
]


def register_opts(conf: cfg.ConfigOpts = cfg.CONF) -> None:
    """Register LoxiLB configuration options with oslo_config."""
    conf.register_group(LOXILB_GROUP)
    conf.register_opts(LOXILB_OPTS, group=LOXILB_GROUP)


def validate_config(conf: cfg.ConfigOpts = cfg.CONF) -> list[str]:
    """Validate LoxiLB configuration values.

    Returns:
        List of error strings if any configuration is invalid, empty list otherwise.
    """
    errors = []
    if not hasattr(conf, "loxilb"):
        return ["Configuration section [loxilb] is missing"]

    loxilb_cfg = conf.loxilb

    if not loxilb_cfg.api_endpoints:
        errors.append("api_endpoints must contain at least one valid endpoint URL")

    if loxilb_cfg.auth_type == constants.AUTH_TYPE_BASIC:
        if not loxilb_cfg.username or not loxilb_cfg.password:
            errors.append("Basic auth requires both 'username' and 'password' to be set")
    elif loxilb_cfg.auth_type == constants.AUTH_TYPE_TOKEN:
        if not loxilb_cfg.api_token:
            errors.append("Token auth requires 'api_token' to be set")
    elif loxilb_cfg.auth_type == constants.AUTH_TYPE_TLS:
        if not loxilb_cfg.tls_client_cert_file or not loxilb_cfg.tls_client_key_file:
            errors.append("TLS auth requires both 'tls_client_cert_file' and 'tls_client_key_file'")

    if loxilb_cfg.api_timeout <= 0:
        errors.append("api_timeout must be a positive integer")

    return errors
