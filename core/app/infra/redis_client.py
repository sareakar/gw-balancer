import json
from typing import Optional

import redis.asyncio as aioredis

from app.config import settings

_redis: Optional[aioredis.Redis] = None

GATEWAY_TTL = 60  # segundos — si el monitor deja de reportar, el gateway queda "oscuro"
APIKEY_CACHE_TTL = 300


async def create_redis() -> aioredis.Redis:
    global _redis
    _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def close_redis():
    global _redis
    if _redis:
        await _redis.aclose()


def get_redis() -> aioredis.Redis:
    return _redis


def _gw_key(tenant_id: str, gateway_slug: str) -> str:
    return f"tenant:{tenant_id}:gateway:{gateway_slug}"


async def set_gateway_state(tenant_id: str, gateway_slug: str, snapshot: dict):
    await _redis.setex(_gw_key(tenant_id, gateway_slug), GATEWAY_TTL, json.dumps(snapshot))


async def get_gateway_state(tenant_id: str, gateway_slug: str) -> Optional[dict]:
    data = await _redis.get(_gw_key(tenant_id, gateway_slug))
    return json.loads(data) if data else None


async def cache_api_key(api_key: str, tenant_id: str):
    await _redis.setex(f"apikey:{api_key}", APIKEY_CACHE_TTL, tenant_id)


async def get_cached_api_key(api_key: str) -> Optional[str]:
    return await _redis.get(f"apikey:{api_key}")
