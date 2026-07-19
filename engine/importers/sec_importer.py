"""Import SEC records requiring ``symbol``, ``filing_date``, and ``source_metadata``."""
from .import_contract import HistoricalSourceImporter
class SECImporter(HistoricalSourceImporter):
    source_name, availability_date_field = "sec", "filing_date"