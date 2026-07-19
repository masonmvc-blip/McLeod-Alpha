"""Import fundamentals records requiring ``symbol``, ``available_date``, and ``source_metadata``."""
from .import_contract import HistoricalSourceImporter
class FundamentalsImporter(HistoricalSourceImporter):
    source_name, availability_date_field = "fundamentals", "available_date"