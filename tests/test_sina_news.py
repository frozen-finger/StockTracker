from datetime import date

from stocktracker.sources.sina_news import SinaFinanceNewsCollector


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class FakeHttp:
    def request(self, method: str, url: str, **kwargs):
        return FakeResponse(
            {
                "result": {
                    "data": [
                        {
                            "docid": "sina-test-1",
                            "title": "某上市公司拟易主，新股东将取得控制权",
                            "intro": "交易完成后实际控制人将发生变更，市场关注后续董事席位调整。",
                            "keywords": "控制权变更,董事席位",
                            "ctime": "1788720000",
                            "url": "https://finance.sina.com.cn/test/1.shtml",
                            "media_name": "新浪财经",
                        }
                    ]
                }
            }
        )


def test_collect_maps_governance_news() -> None:
    collector = SinaFinanceNewsCollector(FakeHttp(), max_pages=1)
    documents = collector.collect(date(2026, 9, 1), date(2026, 9, 10))
    assert len(documents) == 1
    document = documents[0]
    assert document.source_type == "news"
    assert document.source_name == "新浪财经"
    assert "largest_shareholder_change" in document.matched_events
    assert "director_nomination" in document.matched_events
    assert document.content_status == "sina_roll_summary"


def test_collect_filters_outside_window() -> None:
    collector = SinaFinanceNewsCollector(FakeHttp(), max_pages=1)
    documents = collector.collect(date(2026, 1, 1), date(2026, 1, 2))
    assert documents == []
