"""``fundamentals/*.json|jsonl`` records require ``available_date`` and optional ``symbol``."""
from .source_contract import FileBackedConnector
class FundamentalsConnector(FileBackedConnector):
    source_name, source_directory, availability_date_field = "company_fundamentals", "fundamentals", "available_date"