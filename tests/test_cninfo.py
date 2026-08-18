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


class PaginatedHttp:
    def __init__(self) -> None:
        self.pages: list[int] = []

    def request(self, method: str, url: str, **kwargs):
        page = int(kwargs["data"]["pageNum"])
        self.pages.append(page)
        return FakeResponse(
            {
                "hasMore": page == 1,
                "announcements": [
                    {
                        "announcementId": str(page),
                        "announcementTitle": "股东提案",
                        "announcementTime": 1_725_984_000_000,
                        "adjunctUrl": f"finalpage/page-{page}.pdf",
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


def test_query_continues_until_cninfo_has_no_more_results() -> None:
    http = PaginatedHttp()
    collector = CninfoCollector(http)
    items = list(collector._query("股东提案", "szse", date(2024, 9, 1), date(2024, 9, 11)))
    assert [item["announcementId"] for item in items] == ["1", "2"]
    assert http.pages == [1, 2]
    assert collector.warnings == []


def test_optional_page_cap_surfaces_truncation_warning() -> None:
    collector = CninfoCollector(PaginatedHttp(), max_pages=1)
    items = list(collector._query("股东提案", "szse", date(2024, 9, 1), date(2024, 9, 11)))
    assert len(items) == 1
    assert "truncated after 1 pages" in collector.warnings[0]
