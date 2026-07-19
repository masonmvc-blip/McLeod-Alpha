"""Import price records requiring ``symbol``, ``price_date``, and ``source_metadata``."""
from .import_contract import HistoricalSourceImporter
class PriceImporter(HistoricalSourceImporter):
    source_name, availability_date_field = "prices", "price_date"