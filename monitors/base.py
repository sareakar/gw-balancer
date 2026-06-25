from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class GatewaySnapshot:
    available_channels: int
    total_channels: int
    active_calls: int
    failure_rate_5m: float
    registered: bool
    signal_rssi: Optional[int] = None  # dBm


class BaseMonitor(ABC):
    """Un subclass por marca/tipo de gateway. Traduce estado nativo a formato común."""

    def __init__(self, gateway_slug: str):
        self.gateway_slug = gateway_slug

    @abstractmethod
    async def connect(self):
        ...

    @abstractmethod
    async def disconnect(self):
        ...

    @abstractmethod
    async def poll(self) -> GatewaySnapshot:
        """Lee el estado actual del gateway y devuelve un snapshot normalizado."""
        ...

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *args):
        await self.disconnect()
