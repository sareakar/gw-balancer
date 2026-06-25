from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import APIKeyHeader

from app.infra import redis_client, postgres
from app.domain.scoring import score_gateways
from .schemas import (
    GatewayStateReport,
    GatewayScoreItem,
    GatewayStatus,
    RouteDecisionRequest,
    RouteDecisionResponse,
)

router = APIRouter()
_api_key_header = APIKeyHeader(name="X-API-Key")


async def resolve_tenant(api_key: str = Depends(_api_key_header)) -> str:
    tenant_id = await redis_client.get_cached_api_key(api_key)
    if not tenant_id:
        tenant_id = await postgres.get_tenant_by_api_key(api_key)
        if not tenant_id:
            raise HTTPException(status_code=401, detail="Invalid API key")
        await redis_client.cache_api_key(api_key, tenant_id)
    return tenant_id


@router.post("/gateway-state", status_code=204)
async def report_gateway_state(
    report: GatewayStateReport,
    tenant_id: str = Depends(resolve_tenant),
):
    await redis_client.set_gateway_state(
        tenant_id, report.gateway_slug, report.snapshot.model_dump()
    )


@router.post("/route-decision", response_model=RouteDecisionResponse)
async def route_decision(
    request: RouteDecisionRequest,
    tenant_id: str = Depends(resolve_tenant),
):
    gateway_configs = await postgres.get_enabled_gateways(tenant_id)
    if not gateway_configs:
        raise HTTPException(status_code=404, detail="No gateways configured for tenant")

    snapshots = []
    for gw in gateway_configs:
        state = await redis_client.get_gateway_state(tenant_id, gw["slug"])
        if state:
            state["gateway_slug"] = gw["slug"]
            state["cost_per_minute"] = float(gw["cost_per_minute"] or 0)
            snapshots.append(state)

    if not snapshots:
        raise HTTPException(status_code=503, detail="No gateways currently reporting state")

    scores = score_gateways(snapshots)
    if not scores:
        raise HTTPException(status_code=503, detail="All gateways busy or offline")

    best = scores[0]
    await postgres.log_decision(
        tenant_id, request.call_id, best.gateway_slug, best.score, best.reason
    )

    return RouteDecisionResponse(
        gateway_slug=best.gateway_slug,
        score=best.score,
        reason=best.reason,
        alternatives=[
            GatewayScoreItem(gateway_slug=s.gateway_slug, score=s.score)
            for s in scores[1:3]
        ],
    )


@router.get("/gateways", response_model=list[GatewayStatus])
async def list_gateways(tenant_id: str = Depends(resolve_tenant)):
    gateway_configs = await postgres.get_enabled_gateways(tenant_id)
    result = []
    for gw in gateway_configs:
        state = await redis_client.get_gateway_state(tenant_id, gw["slug"])
        result.append(GatewayStatus(
            slug=gw["slug"],
            display_name=gw["display_name"],
            online=state is not None,
            state=state,
        ))
    return result
