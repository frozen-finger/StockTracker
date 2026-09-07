import json
from datetime import date

from stocktracker.sources.eastmoney_news import EastmoneyNewsCollector, _parse_json_or_jsonp


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


def test_parse_jsonp() -> None:
    payload = _parse_json_or_jsonp('jQuery_stocktracker({"result":{"cmsArticleWebOld":[]}})')
    assert payload["result"]["cmsArticleWebOld"] == []


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


def test_collect_filters_outside_window() -> None:
    collector = EastmoneyNewsCollector(FakeHttp(), page_size=50, max_pages=1)
    documents = collector.collect(date(2026, 9, 7), date(2026, 9, 7))
    assert documents == []
