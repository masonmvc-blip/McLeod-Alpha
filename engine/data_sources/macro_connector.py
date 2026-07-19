"""``macro/*.json|jsonl`` records require ``release_date`` and may omit ``symbol``."""
from .source_contract import FileBackedConnector
class MacroConnector(FileBackedConnector):
    source_name, source_directory, availability_date_field = "macro_data", "macro", "release_date"