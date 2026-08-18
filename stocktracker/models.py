from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class Document:
    id: str
    source_type: str
    source_name: str
    title: str
    url: str
    published_at: datetime
    company: str | None = None
    stock_code: str | None = None
    matched_events: list[str] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)
    evidence_snippets: list[str] = field(default_factory=list)
    content_status: str = "metadata_only"

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["published_at"] = self.published_at.isoformat()
        return value

