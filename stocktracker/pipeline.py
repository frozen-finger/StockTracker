from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

from stocktracker.models import Document

LOG = logging.getLogger(__name__)
CHINA_TZ = ZoneInfo("Asia/Shanghai")


class Collector(Protocol):
    name: str

    def collect(self, start: date, end: date) -> list[Document]: ...


def run_pipeline(collectors: list[Collector], start: date, end: date) -> dict:
    documents: dict[str, Document] = {}
    warnings: list[dict[str, str]] = []
    source_stats: dict[str, int] = {}
    hard_failed_sources: set[str] = set()

    for collector in collectors:
        try:
            collected = collector.collect(start, end)
            source_stats[collector.name] = len(collected)
            for warning in getattr(collector, "warnings", []):
                warnings.append({"source": collector.name, "error": warning})
            for document in collected:
                existing = documents.get(document.id)
                if existing is None or len(document.evidence_snippets) > len(existing.evidence_snippets):
                    documents[document.id] = document
        except Exception as error:
            LOG.exception("Collector %s failed", collector.name)
            source_stats[collector.name] = 0
            hard_failed_sources.add(collector.name)
            warnings.append({"source": collector.name, "error": f"{type(error).__name__}: {error}"})

    selected = [document for document in documents.values() if document.matched_events]
    selected.sort(key=lambda document: (document.published_at, document.id), reverse=True)
    event_counts = Counter(event for document in selected for event in document.matched_events)
    status = "complete" if not warnings else (
        "failed" if len(hard_failed_sources) == len(collectors) and not selected else "partial"
    )
    return {
        "schema_version": 1,
        "status": status,
        "generated_at": datetime.now(CHINA_TZ).isoformat(),
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "stats": {
            "document_count": len(selected),
            "source_counts": source_stats,
            "event_counts": dict(sorted(event_counts.items())),
        },
        "warnings": warnings,
        "documents": [document.to_dict() for document in selected],
    }


def write_report(report: dict, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    history_dir = output_dir / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    latest = output_dir / "latest.json"
    snapshot = history_dir / f"{report['window_end']}.json"
    latest.write_text(rendered, encoding="utf-8")
    snapshot.write_text(rendered, encoding="utf-8")
    return latest, snapshot
