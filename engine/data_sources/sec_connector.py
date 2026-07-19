"""``sec/*.json|jsonl`` records require ``filing_date`` and optional ``symbol``."""
from .source_contract import FileBackedConnector
class SECConnector(FileBackedConnector):
    source_name, source_directory, availability_date_field = "sec_filings", "sec", "filing_date"