"""Data models and schemas for LoxiLB REST API payloads."""

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class ServiceArguments:
    """Service arguments representing the frontend definition and service policy in LoxiLB."""

    externalIP: str
    port: int
    protocol: str  # 'tcp', 'udp', 'sctp'
    sel: int = 0  # 0: rr, 1: hash, 2: priority, 3: persist, 4: lc
    mode: int = 1  # 0: dnat, 1: onearm, 2: fullnat, 3: dsr, 4: fullproxy, 5: hostonearm
    monitor: bool = False
    name: str = ""
    probetype: Optional[str] = None  # 'tcp', 'http', 'https', 'ping', 'udp'
    probeport: Optional[int] = None
    probereq: Optional[str] = None
    proberesp: Optional[str] = None
    probeTimeout: Optional[int] = None
    probeRetries: Optional[int] = None
    bgp: Optional[bool] = None
    snat: Optional[bool] = None
    inactiveTimeOut: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict, omitting None values."""
        result = {}
        for k, v in asdict(self).items():
            if v is not None:
                result[k] = v
        return result


@dataclass
class Endpoint:
    """Backend endpoint for a LoxiLB service rule."""

    endpointIP: str
    targetPort: int
    weight: int = 1
    state: Optional[str] = None  # 'active', 'inactive', 'error'

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict, omitting None values."""
        result = {
            "endpointIP": self.endpointIP,
            "targetPort": self.targetPort,
            "weight": self.weight,
        }
        if self.state is not None:
            result["state"] = self.state
        return result


@dataclass
class LoadbalanceEntry:
    """Complete LoadbalanceEntry representing a service rule in LoxiLB."""

    serviceArguments: ServiceArguments
    endpoints: list[Endpoint] = field(default_factory=list)
    secondaryIPs: Optional[list[str]] = None
    allowedSources: Optional[list[str]] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary suitable for JSON serialization."""
        payload: dict[str, Any] = {
            "serviceArguments": self.serviceArguments.to_dict(),
            "endpoints": [ep.to_dict() for ep in self.endpoints],
        }
        if self.secondaryIPs:
            payload["secondaryIPs"] = self.secondaryIPs
        if self.allowedSources:
            payload["allowedSources"] = self.allowedSources
        return payload
