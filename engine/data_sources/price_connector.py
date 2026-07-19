"""``prices/*.json|jsonl`` records require ``price_date`` and optional ``symbol``."""
from .source_contract import FileBackedConnector
class PriceConnector(FileBackedConnector):
    source_name, source_directory, availability_date_field = "prices", "prices", "price_date"