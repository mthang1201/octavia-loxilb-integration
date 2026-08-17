"""Translation package for mapping between Octavia and LoxiLB models."""

from octavia_loxilb.translation.translator import (
    generate_service_name,
    to_loxilb_endpoint,
    to_loxilb_service,
)

__all__ = [
    "to_loxilb_service",
    "to_loxilb_endpoint",
    "generate_service_name",
]
