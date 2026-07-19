"""Import macro records requiring ``release_date`` and ``source_metadata``; symbol is optional."""
from .import_contract import HistoricalSourceImporter
class MacroImporter(HistoricalSourceImporter):
    source_name, availability_date_field, requires_symbol = "macro", "release_date", False