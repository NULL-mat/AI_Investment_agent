"""A-share data integration for the upstream ``hedge_fund`` package.

The extension is intentionally kept outside ``hedge_fund`` so upstream updates
can be merged without carrying A-share-specific changes through the core code.
"""

from .data.client import AShareDataClient
from .data.cached_client import CachedAShareDataClient
from .data.market_analysis import get_csi300_analysis
from .data.market_snapshot import get_market_snapshot

__all__ = [
    "AShareDataClient",
    "CachedAShareDataClient",
    "get_csi300_analysis",
    "get_market_snapshot",
]
