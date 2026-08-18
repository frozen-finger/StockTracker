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

NEWS_SEARCH_TERMS = (
    "A股 权益变动报告书",
    "上市公司 未来12个月 增持",
    "上市公司 提名 董事候选人",
    "上市公司 临时股东大会",
    "上市公司 股东提案",
    "上市公司 股东 临时提案",
    "上市公司 第一大股东 变更",
)


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", value or "").replace("<em>", "").replace("</em>", "")


def classify_text(value: str) -> tuple[list[str], list[str]]:
    normalized = normalize_text(value)
    events: list[str] = []
    keywords: list[str] = []
    for event, aliases in EVENT_KEYWORDS.items():
        hits = [alias for alias in aliases if normalize_text(alias) in normalized]
        if hits:
            events.append(event)
            keywords.extend(hits)
    return events, list(dict.fromkeys(keywords))


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
