from dataclasses import dataclass
from typing import Optional


@dataclass
class GatewaySnapshot:
    available_channels: int
    total_channels: int
    active_calls: int
    failure_rate_5m: float
    registered: bool
    signal_rssi: Optional[int] = None


@dataclass
class GatewayScore:
    gateway_slug: str
    score: float
    reason: str
