from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from stocktracker.http import HttpClient
from stocktracker.keywords import NEWS_SEARCH_TERMS, classify_text, evidence_snippets
from stocktracker.models import Document

LOG = logging.getLogger(__name__)
CHINA_TZ = ZoneInfo("Asia/Shanghai")
EASTMONEY_SEARCH_URL = "https://search-api-web.eastmoney.com/search/jsonp"
EASTMONEY_REFERER = "https://so.eastmoney.com/"


class EastmoneyNewsCollector:
    """Search Eastmoney's public web-news index for governance event coverage."""

    name = "eastmoney_news"

    def __init__(self, http: HttpClient, page_size: int = 50, max_pages: int = 2) -> None:
        if page_size < 1:
            raise ValueError("page_size must be positive")
        if max_pages < 1:
            raise ValueError("max_pages must be positive")
        self.http = http
        self.page_size = page_size
        self.max_pages = max_pages
        self.warnings: list[str] = []

    def collect(self, start: date, end: date) -> list[Document]:
        self.warnings = []
        documents: dict[str, Document] = {}
        successful_queries = 0
        for term in NEWS_SEARCH_TERMS:
            try:
                for item in self._query(term):
                    document = self._from_item(item)
                    local_date = document.published_at.astimezone(CHINA_TZ).date()
                    if start <= local_date <= end and document.matched_events:
                        documents.setdefault(document.id, document)
                successful_queries += 1
            except Exception as error:
                message = f"query term={term!r} failed: {type(error).__name__}: {error}"
                self.warnings.append(message)
                LOG.warning("eastmoney news: %s", message)

        if successful_queries == 0:
            raise RuntimeError("all Eastmoney News queries failed")
        return list(documents.values())

    def _query(self, term: str):
        for page in range(1, self.max_pages + 1):
            callback = "jQuery_stocktracker"
            body = {
                "uid": "",
                "keyword": term,
                "type": ["cmsArticleWebOld"],
                "client": "web",
                "clientType": "web",
                "clientVersion": "curr",
                "params": {
                    "cmsArticleWebOld": {
                        "searchScope": "default",
                        "sort": "default",
                        "pageIndex": page,
                        "pageSize": self.page_size,
                        "preTag": "<em>",
                        "postTag": "</em>",
                    }
                },
            }
            response = self.http.request(
                "GET",
                EASTMONEY_SEARCH_URL,
                params={
                    "cb": callback,
                    "param": json.dumps(body, ensure_ascii=False, separators=(",", ":")),
                },
                headers={"Referer": EASTMONEY_REFERER},
            )
            payload = _parse_json_or_jsonp(response.text)
            result = payload.get("result") if isinstance(payload, dict) else None
            rows = result.get("cmsArticleWebOld") if isinstance(result, dict) else None
            if not isinstance(rows, list) or not rows:
                break
            yield from (item for item in rows if isinstance(item, dict))
            if len(rows) < self.page_size:
                break

    def _from_item(self, item: dict[str, Any]) -> Document:
        title = _clean_html(item.get("title"))
        content = _clean_html(item.get("content"))
        url = str(item.get("url") or "").strip()
        published_at = _parse_datetime(item.get("date"))
        events, keywords = classify_text(f"{title}\n{content}")
        identity_seed = url or f"{title}|{published_at.isoformat()}"
        identity = hashlib.sha256(identity_seed.encode("utf-8")).hexdigest()[:24]
        return Document(
            id=f"news:{identity}",
            source_type="news",
            source_name=str(item.get("mediaName") or "东方财富新闻搜索").strip(),
            title=title,
            url=url,
            published_at=published_at,
            matched_events=events,
            matched_keywords=keywords,
            evidence_snippets=evidence_snippets(content, keywords),
            content_status="eastmoney_search_summary",
        )


def _parse_json_or_jsonp(text: str) -> Any:
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        match = re.match(r"^[A-Za-z0-9_$]+\((.*)\)\s*;?\s*$", stripped, re.DOTALL)
        if not match:
            raise ValueError("response is neither JSON nor JSONP")
        return json.loads(match.group(1))


def _clean_html(value: Any) -> str:
    return BeautifulSoup(str(value or ""), "html.parser").get_text(" ", strip=True)


def _parse_datetime(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime.combine(date.today(), time.min, CHINA_TZ)

    normalized = text.replace("/", "-")
    candidates = (
        normalized,
        normalized.replace("T", " "),
    )
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=CHINA_TZ)
            return parsed.astimezone(CHINA_TZ)
        except ValueError:
            pass

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(normalized, fmt).replace(tzinfo=CHINA_TZ)
        except ValueError:
            pass
    raise ValueError(f"unsupported Eastmoney date: {text!r}")
