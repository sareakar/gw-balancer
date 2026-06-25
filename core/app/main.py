from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.infra import redis_client, postgres
from app.api.v1.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await redis_client.create_redis()
    await postgres.create_pool()
    yield
    await redis_client.close_redis()
    await postgres.close_pool()


app = FastAPI(title="GW Balancer Core", version="0.1.0", lifespan=lifespan)
app.include_router(router, prefix="/v1")


@app.get("/health")
async def health():
    return {"status": "ok"}
