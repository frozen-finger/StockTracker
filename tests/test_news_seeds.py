from datetime import datetime
from zoneinfo import ZoneInfo

from stocktracker.models import Document
from stocktracker.sources.news_seeds import build_news_seeds


class Provider:
    def __init__(self, documents):
        self.last_documents = documents


def doc(identity: str, company: str, code: str, event: str, hour: int = 9) -> Document:
    return Document(
        id=identity,
        source_type="official",
        source_name="fixture",
        title=identity,
        url=f"https://example.com/{identity}",
        published_at=datetime(2026, 9, 7, hour, tzinfo=ZoneInfo("Asia/Shanghai")),
        company=company,
        stock_code=code,
        matched_events=[event],
    )


def test_seed_builder_prioritizes_control_events_and_deduplicates_company() -> None:
    provider = Provider(
        [
            doc("meeting", "普通会议公司", "000001", "extraordinary_general_meeting"),
            doc("equity", "权益公司", "000002", "equity_change_report"),
            doc("control-old", "控制公司", "000003", "largest_shareholder_change", 8),
            doc("control-new", "控制公司", "000003", "largest_shareholder_change", 10),
        ]
    )
    seeds = build_news_seeds([provider], limit=10)
    assert [seed.stock_code for seed in seeds] == ["000003", "000002"]
    assert seeds[0].query == "控制公司"


def test_seed_builder_respects_limit() -> None:
    provider = Provider(
        [
            doc("a", "A公司", "000001", "largest_shareholder_change"),
            doc("b", "B公司", "000002", "equity_change_report"),
        ]
    )
    seeds = build_news_seeds([provider], limit=1)
    assert len(seeds) == 1
    assert seeds[0].company == "A公司"
