from __future__ import annotations

import re
from collections import OrderedDict


EVENT_KEYWORDS: OrderedDict[str, tuple[str, ...]] = OrderedDict(
    {
        "equity_change_report": (
            "权益变动报告书",
            "简式权益变动报告书",
            "详式权益变动报告书",
        ),
        "future_12m_increase": (
            "未来12个月内增持",
            "未来十二个月内增持",
            "未来12个月继续增持",
            "未来十二个月继续增持",
            "未来 12 个月内增持",
        ),
        "director_nomination": (
            "提名董事",
            "董事候选人",
            "非独立董事候选人",
            "独立董事候选人",
        ),
        "extraordinary_general_meeting": (
            "临时股东大会",
            "临时股东会",
        ),
        "shareholder_proposal": (
            "股东提案",
            "临时提案",
            "增加临时提案",
            "提请增加临时提案",
        ),
        "largest_shareholder_change": (
            "第一大股东变更",
            "第一大股东发生变更",
            "变更为第一大股东",
            "成为第一大股东",
            "控股股东变更",
        ),
    }
)

# Media coverage often uses shorter or more colloquial governance wording than
# formal exchange disclosures. Keep these aliases news-only so official filings
# continue to use the stricter EVENT_KEYWORDS taxonomy above.
NEWS_EVENT_KEYWORDS: OrderedDict[str, tuple[str, ...]] = OrderedDict(
    {
        "equity_change_report": (
            "权益变动",
            "举牌",
            "持股比例变动",
        ),
        "future_12m_increase": (
            "增持计划",
            "拟增持",
            "计划增持",
            "承诺增持",
        ),
        "director_nomination": (
            "董事提名",
            "提名董事",
            "董事候选人",
            "董事席位",
        ),
        "extraordinary_general_meeting": (
            "临时股东大会",
            "临时股东会",
        ),
        "shareholder_proposal": (
            "股东提案",
            "临时提案",
            "增加临时提案",
        ),
        "largest_shareholder_change": (
            "第一大股东变更",
            "控股股东变更",
            "实际控制人变更",
            "实际控制人将发生变更",
            "实控人变更",
            "实控人拟变更",
            "控制权变更",
            "控制权拟变更",
            "控制权将发生变更",
            "取得控制权",
            "将取得控制权",
            "将成为控股股东",
            "将成为实际控制人",
            "易主",
        ),
    }
)

CNINFO_SEARCH_TERMS = (
    "权益变动报告书",
    "董事候选人",
    "临时股东大会",
    "临时股东会",
    "股东提案",
    "临时提案",
    "第一大股东",
    "控股股东变更",
)

CNINFO_TERM_EVENTS = {
    "权益变动报告书": "equity_change_report",
    "董事候选人": "director_nomination",
    "临时股东大会": "extraordinary_general_meeting",
    "临时股东会": "extraordinary_general_meeting",
    "股东提案": "shareholder_proposal",
    "临时提案": "shareholder_proposal",
    "第一大股东": "largest_shareholder_change",
    "控股股东变更": "largest_shareholder_change",
}

# Search engines and finance portals tend to perform better with compact terms
# than with sentence-like queries such as "上市公司 ...".
NEWS_SEARCH_TERMS = (
    "权益变动",
    "增持计划",
    "董事候选人",
    "临时股东会",
    "股东提案",
    "临时提案",
    "第一大股东",
    "控股股东变更",
    "实控人变更",
    "控制权变更",
)


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", value or "").replace("<em>", "").replace("</em>", "")


def _classify_with_keywords(
    value: str,
    keyword_map: OrderedDict[str, tuple[str, ...]],
) -> tuple[list[str], list[str]]:
    normalized = normalize_text(value)
    events: list[str] = []
    keywords: list[str] = []
    for event, aliases in keyword_map.items():
        hits = [alias for alias in aliases if normalize_text(alias) in normalized]
        if hits:
            events.append(event)
            keywords.extend(hits)
    return events, list(dict.fromkeys(keywords))


def classify_text(value: str) -> tuple[list[str], list[str]]:
    return _classify_with_keywords(value, EVENT_KEYWORDS)


def classify_news_text(value: str) -> tuple[list[str], list[str]]:
    # Include strict aliases too, then add media-specific synonyms.
    strict_events, strict_keywords = _classify_with_keywords(value, EVENT_KEYWORDS)
    news_events, news_keywords = _classify_with_keywords(value, NEWS_EVENT_KEYWORDS)
    return (
        list(dict.fromkeys([*strict_events, *news_events])),
        list(dict.fromkeys([*strict_keywords, *news_keywords])),
    )


def evidence_snippets(text: str, keywords: list[str], radius: int = 90, limit: int = 4) -> list[str]:
    compact = re.sub(r"\s+", " ", text or "").strip()
    snippets: list[str] = []
    for keyword in keywords:
        match = re.search(re.escape(keyword).replace(r"\ ", r"\s*"), compact)
        if not match:
            continue
        start = max(0, match.start() - radius)
        end = min(len(compact), match.end() + radius)
        snippet = compact[start:end].strip(" ，。；;\n")
        if snippet and snippet not in snippets:
            snippets.append(snippet)
        if len(snippets) >= limit:
            break
    return snippets
