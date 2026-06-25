from dataclasses import dataclass
from typing import Optional
from .models import GatewayScore


@dataclass
class ScoringWeights:
    available_channels: float = 0.40
    signal_rssi: float = 0.30
    failure_rate: float = 0.20
    cost: float = 0.10


def _channel_score(available: int, total: int) -> float:
    return (available / total * 100) if total > 0 else 0.0


def _rssi_score(rssi: Optional[int]) -> float:
    if rssi is None:
        return 50.0  # neutral when unknown
    # -50 dBm → 100, -110 dBm → 0
    return max(0.0, min(100.0, (rssi + 110) * (100 / 60)))


def _failure_score(failure_rate: float) -> float:
    return max(0.0, (1 - failure_rate) * 100)


def _cost_score(cost: Optional[float], max_cost: float) -> float:
    if cost is None or max_cost == 0:
        return 50.0  # neutral when unknown
    return max(0.0, (1 - cost / max_cost) * 100)


def score_gateways(
    snapshots: list[dict],
    weights: ScoringWeights | None = None,
) -> list[GatewayScore]:
    if weights is None:
        weights = ScoringWeights()

    costs = [s["cost_per_minute"] for s in snapshots if s.get("cost_per_minute") is not None]
    max_cost = max(costs) if costs else 1.0

    results = []
    for snap in snapshots:
        if not snap.get("registered", True):
            continue
        if snap.get("available_channels", 0) == 0:
            continue

        score = (
            _channel_score(snap.get("available_channels", 0), snap.get("total_channels", 1))
            * weights.available_channels
            + _rssi_score(snap.get("signal_rssi"))
            * weights.signal_rssi
            + _failure_score(snap.get("failure_rate_5m", 0.0))
            * weights.failure_rate
            + _cost_score(snap.get("cost_per_minute"), max_cost)
            * weights.cost
        )

        results.append(GatewayScore(
            gateway_slug=snap["gateway_slug"],
            score=round(score, 2),
            reason="weighted_score",
        ))

    return sorted(results, key=lambda x: x.score, reverse=True)
