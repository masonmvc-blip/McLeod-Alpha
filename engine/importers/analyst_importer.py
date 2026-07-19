"""Import analyst records requiring ``symbol``, ``revision_date``, and ``source_metadata``."""
from .import_contract import HistoricalSourceImporter
class AnalystImporter(HistoricalSourceImporter):
    source_name, availability_date_field = "analysts", "revision_date"