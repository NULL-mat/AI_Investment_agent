"""A-share data providers and the ``hedge_fund`` protocol adapter."""

from .client import AShareDataClient
from .cached_client import CachedAShareDataClient
from .market_analysis import get_csi300_analysis
from .market_snapshot import get_market_snapshot

__all__ = [
    "AShareDataClient",
    "CachedAShareDataClient",
    "get_csi300_analysis",
    "get_market_snapshot",
]
