from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable

from stocktracker.models import Document
from stocktracker.sources.exchanges import ExchangeFallbackCollector, FallbackAwareCninfoCollector

# Lower number = higher value for media follow-up. Pure meeting notices are
# intentionally excluded because they dominate the official dataset but rarely
# add useful context for the weekly governance report.
EVENT_PRIORITY = {
    "largest_shareholder_change": 0,
    "equity_change_report": 1,
    "future_12m_increase": 2,
    "shareholder_proposal": 3,
    "director_nomination": 4,
}


@dataclass(frozen=True, slots=True)
class NewsSeed:
    query: str
    company: str | None
    stock_code: str | None
    matched_events: tuple[str, ...]


class SeededCninfoCollector(FallbackAwareCninfoCollector):
    """CNInfo collector that exposes collected documents to later news collectors."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.last_documents: list[Document] = []

    def collect(self, start: date, end: date) -> list[Document]:
        self.last_documents = []
        documents = super().collect(start, end)
        self.last_documents = documents
        return documents


class SeededExchangeFallbackCollector(ExchangeFallbackCollector):
    """Exchange fallback that exposes recovered documents as news search seeds."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.last_documents: list[Document] = []

    def collect(self, start: date, end: date) -> list[Document]:
        self.last_documents = []
        documents = super().collect(start, end)
        self.last_documents = documents
        return documents


def build_news_seeds(providers: Iterable[Any], limit: int = 30) -> list[NewsSeed]:
    if limit < 1:
        return []

    candidates: list[Document] = []
    for provider in providers:
        candidates.extend(getattr(provider, "last_documents", []) or [])

    def priority(document: Document) -> tuple[int, float]:
        scores = [EVENT_PRIORITY[event] for event in document.matched_events if event in EVENT_PRIORITY]
        best = min(scores) if scores else 999
        return best, -document.published_at.timestamp()

    candidates.sort(key=priority)
    seen: set[str] = set()
    seeds: list[NewsSeed] = []
    for document in candidates:
        relevant_events = tuple(event for event in document.matched_events if event in EVENT_PRIORITY)
        if not relevant_events:
            continue
        company = (document.company or "").strip() or None
        stock_code = (document.stock_code or "").strip() or None
        query = company or stock_code
        if not query:
            continue
        # Prefer the stock code as the stable identity when present, while using
        # the company name as the human-friendly search term.
        identity = stock_code or company or query
        if identity in seen:
            continue
        seen.add(identity)
        seeds.append(
            NewsSeed(
                query=query,
                company=company,
                stock_code=stock_code,
                matched_events=relevant_events,
            )
        )
        if len(seeds) >= limit:
            break
    return seeds
