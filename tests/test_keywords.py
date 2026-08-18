from stocktracker.keywords import classify_text, evidence_snippets


def test_classifies_multiple_events() -> None:
    text = "信息披露义务人拟在未来12个月内增持，并提交详式权益变动报告书。"
    events, keywords = classify_text(text)
    assert events == ["equity_change_report", "future_12m_increase"]
    assert "未来12个月内增持" in keywords


def test_evidence_is_bounded() -> None:
    text = "前文" * 100 + "第一大股东发生变更" + "后文" * 100
    snippets = evidence_snippets(text, ["第一大股东发生变更"], radius=20)
    assert len(snippets) == 1
    assert "第一大股东发生变更" in snippets[0]
    assert len(snippets[0]) < 80

