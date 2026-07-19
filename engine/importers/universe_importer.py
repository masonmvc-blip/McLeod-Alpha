"""Import index membership records requiring ``symbol``, ``membership_date``, and ``source_metadata``."""
from .import_contract import HistoricalSourceImporter
class UniverseImporter(HistoricalSourceImporter):
    source_name, availability_date_field = "universes", "membership_date"