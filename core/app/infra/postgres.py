from typing import Optional
from uuid import UUID

import asyncpg

from app.config import settings

_pool: Optional[asyncpg.Pool] = None


async def create_pool() -> asyncpg.Pool:
    global _pool
    _pool = await asyncpg.create_pool(settings.database_url, min_size=2, max_size=10)
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()


def get_pool() -> asyncpg.Pool:
    return _pool


async def get_tenant_by_api_key(api_key: str) -> Optional[str]:
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT tenant_id::text FROM api_keys WHERE key = $1 AND revoked_at IS NULL",
            api_key,
        )
    return row["tenant_id"] if row else None


async def get_enabled_gateways(tenant_id: str) -> list[dict]:
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT slug, display_name, cost_per_minute "
            "FROM gateways WHERE tenant_id = $1 AND enabled = TRUE",
            UUID(tenant_id),
        )
    return [dict(r) for r in rows]


async def log_decision(
    tenant_id: str,
    call_id: Optional[str],
    gateway_slug: str,
    score: float,
    reason: str,
):
    async with _pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO route_decisions (tenant_id, call_id, gateway_slug, score, reason) "
            "VALUES ($1, $2, $3, $4, $5)",
            UUID(tenant_id), call_id, gateway_slug, score, reason,
        )
