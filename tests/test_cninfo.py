from datetime import date

from stocktracker.sources.cninfo import CninfoCollector


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class FakeHttp:
    def __init__(self) -> None:
        self.calls = 0

    def request(self, method: str, url: str, **kwargs):
        self.calls += 1
        return FakeResponse(
            {
                "hasMore": False,
                "announcements": [
                    {
                        "announcementId": "123",
                        "announcementTitle": "<em>简式权益变动报告书</em>",
                        "announcementTime": 1_725_984_000_000,
                        "adjunctUrl": "finalpage/2024-09-11/test.pdf",
                        "secName": "示例股份",
                        "secCode": "000001",
                    }
                ],
            }
        )


def test_query_and_mapping() -> None:
    collector = CninfoCollector(FakeHttp())
    items = list(collector._query("权益变动报告书", "szse", date(2024, 9, 1), date(2024, 9, 11)))
    document = collector._from_item(items[0])
    assert document.id == "cninfo:123"
    assert document.stock_code == "000001"
    assert document.source_type == "official"
    assert document.matched_events == ["equity_change_report"]
    assert document.url == "https://static.cninfo.com.cn/finalpage/2024-09-11/test.pdf"

