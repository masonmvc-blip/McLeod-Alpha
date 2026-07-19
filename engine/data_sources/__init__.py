"""Data-source integrations and deterministic local historical connectors."""

from .analyst_connector import AnalystConnector
from .fundamentals_connector import FundamentalsConnector
from .macro_connector import MacroConnector
from .news_connector import NewsConnector
from .price_connector import PriceConnector
from .sec_connector import SECConnector
from .source_contract import HistoricalSourceConnector, SourceFragment, SourceValidationError

__all__ = (
    "AnalystConnector", "FundamentalsConnector", "HistoricalSourceConnector",
    "MacroConnector", "NewsConnector", "PriceConnector", "SECConnector",
    "SourceFragment", "SourceValidationError",
)