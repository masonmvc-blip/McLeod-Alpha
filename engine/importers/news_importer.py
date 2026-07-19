"""Import news records requiring ``symbol``, ``published_at``, and ``source_metadata``."""
from .import_contract import HistoricalSourceImporter
class NewsImporter(HistoricalSourceImporter):
    source_name, availability_date_field = "news", "published_at"