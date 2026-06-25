from typing import Optional, Any
from pydantic import BaseModel


class GatewaySnapshot(BaseModel):
    available_channels: int
    total_channels: int
    signal_rssi: Optional[int] = None  # dBm
    active_calls: int = 0
    failure_rate_5m: float = 0.0  # 0.0 – 1.0
    registered: bool = True


class GatewayStateReport(BaseModel):
    gateway_slug: str
    snapshot: GatewaySnapshot


class RouteDecisionRequest(BaseModel):
    call_id: Optional[str] = None


class GatewayScoreItem(BaseModel):
    gateway_slug: str
    score: float


class RouteDecisionResponse(BaseModel):
    gateway_slug: str
    score: float
    reason: str
    alternatives: list[GatewayScoreItem] = []


class GatewayStatus(BaseModel):
    slug: str
    display_name: str
    online: bool
    state: Optional[dict[str, Any]] = None
