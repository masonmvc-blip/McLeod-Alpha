from __future__ import annotations

from typing import Iterable


def normalize_tags(tags: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({str(tag).strip() for tag in tags if str(tag).strip()}))