"""Adapters that integrate TradingAgents without modifying either core."""

from .data_hub import MultiSourceDataError, MultiSourceDataHub
from .models import DataBundle, SourceEvidence, SourceFailure
from .providers import (
    AShareProvider,
    FinancialDatasetsProvider,
    NewsEngineProvider,
    TradingAgentsVendorError,
    TradingAgentsProvider,
)

__all__ = [
    "AShareProvider",
    "DataBundle",
    "FinancialDatasetsProvider",
    "MultiSourceDataHub",
    "MultiSourceDataError",
    "NewsEngineProvider",
    "SourceEvidence",
    "SourceFailure",
    "TradingAgentsVendorError",
    "TradingAgentsProvider",
]
