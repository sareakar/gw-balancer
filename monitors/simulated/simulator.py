"""Monitor simulado — genera snapshots realistas falsos para el laboratorio."""
import asyncio
import logging
import os
import random

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("monitor-sim")

CORE_URL = os.getenv("CORE_URL", "http://localhost:8000")
API_KEY = os.getenv("API_KEY", "")
INTERVAL = int(os.getenv("REPORT_INTERVAL", "10"))
GATEWAYS = os.getenv("GATEWAY_SLUGS", "gw-001,gw-002,gw-003").split(",")


def _fake_snapshot(slug: str) -> dict:
    total = random.choice([4, 8, 16])
    active = random.randint(0, total)
    return {
        "gateway_slug": slug,
        "snapshot": {
            "available_channels": total - active,
            "total_channels": total,
            "signal_rssi": random.randint(-95, -55),
            "active_calls": active,
            "failure_rate_5m": round(random.uniform(0.0, 0.12), 3),
            "registered": random.random() > 0.05,  # 95% uptime
        },
    }


async def report_once(client: httpx.AsyncClient):
    for slug in GATEWAYS:
        payload = _fake_snapshot(slug)
        snap = payload["snapshot"]
        try:
            resp = await client.post(
                f"{CORE_URL}/v1/gateway-state",
                json=payload,
                headers={"X-API-Key": API_KEY},
                timeout=5.0,
            )
            resp.raise_for_status()
            log.info(
                "%s  ch=%d/%d  rssi=%d  fail=%.1f%%  reg=%s",
                slug,
                snap["available_channels"],
                snap["total_channels"],
                snap["signal_rssi"],
                snap["failure_rate_5m"] * 100,
                snap["registered"],
            )
        except Exception as exc:
            log.warning("%s  error: %s", slug, exc)


async def main():
    log.info("Simulated monitor starting — gateways: %s  interval: %ds", GATEWAYS, INTERVAL)
    async with httpx.AsyncClient() as client:
        while True:
            await report_once(client)
            await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
