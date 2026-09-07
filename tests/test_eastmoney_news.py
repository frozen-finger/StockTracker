import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from stocktracker.models import Document
from stocktracker.sources.eastmoney_news import EastmoneyNewsCollector, _extract_rows, _parse_json_or_jsonp


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeHttp:
    def __init__(self) -> None:
        self.calls = 0

    def request(self, method: str, url: str, **kwargs):
        self.calls += 1
        payload = {
            "result": {
                "cmsArticleWebOld": [
                    {
                        "title": "示例公司控股股东变更，治理结构或调整",
                        "content": "公司公告显示控股股东变更，市场关注后续董事会安排。",
                        "date": "2026-09-06 10:30:00",
                        "mediaName": "东方财富网",
                        "url": "https://finance.eastmoney.com/a/test.html",
                    }
                ]
            }
        }
        return FakeResponse(f"jQuery_stocktracker({json.dumps(payload, ensure_ascii=False)})")


class SeedProvider:
    def __init__(self) -> None:
        self.last_documents = [
            Document(
                id="official:1",
                source_type="official",
                source_name="fixture",
                title="关于控制权拟发生变更的公告",
                url="https://example.com/official",
                published_at=datetime(2026, 9, 7, tzinfo=ZoneInfo("Asia/Shanghai")),
                company="宇邦新材",
                stock_code="301266",
                matched_events=["largest_shareholder_change"],
            )
        ]


class SeedAwareHttp:
    def request(self, method: str, url: str, **kwargs):
        body = json.loads(kwargs["params"]["param"])
        keyword = body["keyword"]
        rows = []
        if keyword == "宇邦新材":
            rows = [
                {
                    "title": "宇邦新材控制权拟变更！收购方刚成立不到10天",
                    "content": "交易完成后公司控制权将发生变更，市场关注新实际控制人后续安排。",
                    "date": "2026-09-07 09:30:00",
                    "mediaName": "证券时报",
                    "url": "https://finance.eastmoney.com/a/seed-test.html",
                }
            ]
        # Exercise the alternate {list:[...]} response shape.
        payload = {"result": {"cmsArticleWebOld": {"list": rows}}}
        return FakeResponse(f"jQuery_stocktracker({json.dumps(payload, ensure_ascii=False)})")


def test_parse_jsonp() -> None:
    payload = _parse_json_or_jsonp('jQuery_stocktracker({"result":{"cmsArticleWebOld":[]}})')
    assert payload["result"]["cmsArticleWebOld"] == []


def test_extract_rows_supports_object_list_shape() -> None:
    payload = {"result": {"cmsArticleWebOld": {"list": [{"title": "x"}]}}}
    assert _extract_rows(payload) == [{"title": "x"}]


def test_collect_maps_and_deduplicates_news() -> None:
    http = FakeHttp()
    collector = EastmoneyNewsCollector(http, page_size=50, max_pages=1)
    documents = collector.collect(date(2026, 8, 31), date(2026, 9, 7))

    assert len(documents) == 1
    document = documents[0]
    assert document.source_type == "news"
    assert document.source_name == "东方财富网"
    assert document.title == "示例公司控股股东变更，治理结构或调整"
    assert document.matched_events == ["largest_shareholder_change"]
    assert document.content_status == "eastmoney_search_summary"
    assert document.url == "https://finance.eastmoney.com/a/test.html"
    assert collector.warnings == []


def test_collect_uses_high_signal_company_seed_and_attaches_identity() -> None:
    collector = EastmoneyNewsCollector(
        SeedAwareHttp(),
        page_size=20,
        max_pages=1,
        seed_providers=[SeedProvider()],
        seed_limit=10,
    )
    documents = collector.collect(date(2026, 8, 31), date(2026, 9, 7))
    assert len(documents) == 1
    document = documents[0]
    assert document.company == "宇邦新材"
    assert document.stock_code == "301266"
    assert document.source_name == "证券时报"
    assert "largest_shareholder_change" in document.matched_events


def test_collect_filters_outside_window() -> None:
    collector = EastmoneyNewsCollector(FakeHttp(), page_size=50, max_pages=1)
    documents = collector.collect(date(2026, 9, 7), date(2026, 9, 7))
    assert documents == []
