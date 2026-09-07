from datetime import date

from stocktracker.sources.exchanges import ExchangeFallbackCollector


class FakePrimary:
    name = "cninfo"
    failed = False
    failed_queries = {
        ("董事候选人", "sse"),
        ("临时股东大会", "sse"),
        ("股东提案", "szse"),
    }
    failed_query_errors = {
        key: f"primary failed: {key[0]}:{key[1]}" for key in failed_queries
    }


class FakeExchangeCollector:
    def __init__(self, name: str, failed_terms: set[str] | None = None) -> None:
        self.name = name
        self.failed_terms = failed_terms or set()
        self.warnings: list[str] = []
        self.calls: list[list[str]] = []

    def collect_terms(self, terms, start: date, end: date):
        self.calls.append(list(terms))
        return []


def test_fallback_only_queries_failed_term_exchange_pairs() -> None:
    sse = FakeExchangeCollector("sse")
    szse = FakeExchangeCollector("szse")
    bse = FakeExchangeCollector("bse")
    primary = FakePrimary()
    fallback = ExchangeFallbackCollector(object(), primary, collectors=[sse, szse, bse])

    documents = fallback.collect(date(2026, 8, 31), date(2026, 9, 7))

    assert documents == []
    assert sse.calls == [["临时股东大会", "董事候选人"]]
    assert szse.calls == [["股东提案"]]
    assert bse.calls == []
    assert fallback.recovered_queries == primary.failed_queries
    assert fallback.unrecovered_queries == set()
    assert fallback.resolved_warnings["cninfo"] == set(primary.failed_query_errors.values())


def test_unrecovered_fallback_query_keeps_primary_warning() -> None:
    sse = FakeExchangeCollector("sse", failed_terms={"董事候选人"})
    szse = FakeExchangeCollector("szse")
    primary = FakePrimary()
    fallback = ExchangeFallbackCollector(object(), primary, collectors=[sse, szse])

    fallback.collect(date(2026, 8, 31), date(2026, 9, 7))

    assert ("董事候选人", "sse") in fallback.unrecovered_queries
    assert primary.failed_query_errors[("董事候选人", "sse")] not in fallback.resolved_warnings["cninfo"]
