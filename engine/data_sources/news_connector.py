"""``news/*.json|jsonl`` records require ``published_at`` and optional ``symbol``."""
from .source_contract import FileBackedConnector
class NewsConnector(FileBackedConnector):
    source_name, source_directory, availability_date_field = "evidence", "news", "published_at"