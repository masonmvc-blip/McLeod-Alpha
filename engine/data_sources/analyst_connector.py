"""``analysts/*.json|jsonl`` records require ``revision_date`` and optional ``symbol``."""
from .source_contract import FileBackedConnector
class AnalystConnector(FileBackedConnector):
    source_name, source_directory, availability_date_field = "analyst_estimates", "analysts", "revision_date"