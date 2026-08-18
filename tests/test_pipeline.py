import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from stocktracker.models import Document
from stocktracker.pipeline import run_pipeline, write_report


class GoodCollector:
    name = "good"

    def collect(self, start: date, end: date):
        return [
            Document(
                id="test:1",
                source_type="official",
                source_name="fixture",
                title="关于召开临时股东大会的通知",
                url="https://example.com/1",
                published_at=datetime(2026, 8, 16, tzinfo=ZoneInfo("Asia/Shanghai")),
                matched_events=["extraordinary_general_meeting"],
                matched_keywords=["临时股东大会"],
            )
        ]


class BrokenCollector:
    name = "broken"

    def collect(self, start: date, end: date):
        raise RuntimeError("source unavailable")


def test_partial_report_and_write(tmp_path) -> None:
    report = run_pipeline([GoodCollector(), BrokenCollector()], date(2026, 8, 10), date(2026, 8, 17))
    assert report["status"] == "partial"
    assert report["stats"]["document_count"] == 1
    assert report["warnings"][0]["source"] == "broken"

    latest, snapshot = write_report(report, tmp_path)
    assert latest.exists() and snapshot.exists()
    assert json.loads(latest.read_text(encoding="utf-8"))["schema_version"] == 1


def test_failed_when_every_source_is_unavailable() -> None:
    report = run_pipeline([BrokenCollector()], date(2026, 8, 10), date(2026, 8, 17))
    assert report["status"] == "failed"
    assert report["documents"] == []
