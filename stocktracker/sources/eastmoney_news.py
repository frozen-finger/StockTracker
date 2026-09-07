from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import date, datetime, time
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from stocktracker.http import HttpClient
from stocktracker.keywords import NEWS_SEARCH_TERMS, classify_news_text, evidence_snippets
from stocktracker.models import Document
from stocktracker.sources.news_seeds import NewsSeed, build_news_seeds

LOG = logging.getLogger(__name__)
CHINA_TZ = ZoneInfo("Asia/Shanghai")
EASTMONEY_SEARCH_URL = "https://search-api-web.eastmoney.com/search/jsonp"
EASTMONEY_REFERER = "https://so.eastmoney.com/"


class EastmoneyNewsCollector:
    """Search Eastmoney's public web-news index for governance event coverage."""

    name = "eastmoney_news"

    def __init__(
        self,
        http: HttpClient,
        page_size: int = 30,
        max_pages: int = 1,
        seed_providers: Iterable[Any] | None = None,
        seed_limit: int = 30,
    ) -> None:
        if page_size < 1:
            raise ValueError("page_size must be positive")
        if max_pages < 1:
            raise ValueError("max_pages must be positive")
        self.http = http
        self.page_size = page_size
        self.max_pages = max_pages
        self.seed_providers = list(seed_providers or [])
        self.seed_limit = seed_limit
        self.warnings: list[str] = []
        self._body_key: str | None = None

    def collect(self, start: date, end: date) -> list[Document]:
        self.warnings = []
        documents: dict[str, Document] = {}
        successful_queries = 0

        # Broad searches are useful when no formal filing exists yet.
        for term in NEWS_SEARCH_TERMS:
            successful_queries += self._collect_query(term, start, end, documents)

        # Formal filings provide far better search anchors than generic governance
        # words. Search the highest-signal companies directly and attach their
        # company/code metadata to matching media coverage.
        seeds = build_news_seeds(self.seed_providers, limit=self.seed_limit)
        for seed in seeds:
            successful_queries += self._collect_query(seed.query, start, end, documents, seed=seed)

        if successful_queries == 0:
            raise RuntimeError("all Eastmoney News queries failed")
        if seeds:
            LOG.info("Eastmoney news searched %s high-signal company seeds", len(seeds))
        return list(documents.values())

    def _collect_query(
        self,
        term: str,
        start: date,
        end: date,
        documents: dict[str, Document],
        *,
        seed: NewsSeed | None = None,
    ) -> int:
        try:
            for item in self._query(term):
                document = self._from_item(item)
                local_date = document.published_at.astimezone(CHINA_TZ).date()
                if not (start <= local_date <= end) or not document.matched_events:
                    continue
                if seed is not None:
                    document.company = seed.company
                    document.stock_code = seed.stock_code
                documents.setdefault(document.id, document)
            return 1
        except Exception as error:
            message = f"query term={term!r} failed: {type(error).__name__}: {error}"
            self.warnings.append(message)
            LOG.warning("eastmoney news: %s", message)
            return 0

    def _query(self, term: str):
        for page in range(1, self.max_pages + 1):
            rows = self._query_page(term, page)
            if not rows:
                break
            yield from rows
            if len(rows) < self.page_size:
                break

    def _query_page(self, term: str, page: int) -> list[dict[str, Any]]:
        # Eastmoney has served two closely related request schemas in the wild:
        # `params` with an array result and `param` with a {list:[...]} result.
        # Probe once, remember the working schema, and parse both response shapes.
        body_keys = [self._body_key] if self._body_key else ["params", "param"]
        for body_key in body_keys:
            if body_key is None:
                continue
            callback = "jQuery_stocktracker"
            search_config = {
                "searchScope": "default",
                "sort": "default",
                "pageIndex": page,
                "pageSize": self.page_size,
                "preTag": "<em>",
                "postTag": "</em>",
            }
            body = {
                "uid": "",
                "keyword": term,
                "type": ["cmsArticleWebOld"],
                "client": "web",
                "clientType": "web",
                "clientVersion": "curr",
                body_key: {"cmsArticleWebOld": search_config},
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
            rows = _extract_rows(payload)
            if rows:
                self._body_key = body_key
                return rows
        return []

    def _from_item(self, item: dict[str, Any]) -> Document:
        title = _clean_html(item.get("title"))
        content = _clean_html(item.get("content"))
        url = str(item.get("url") or "").strip()
        published_at = _parse_datetime(item.get("date"))
        events, keywords = classify_news_text(f"{title}\n{content}")
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


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    result = payload.get("result") if isinstance(payload, dict) else None
    cms = result.get("cmsArticleWebOld") if isinstance(result, dict) else None
    if isinstance(cms, list):
        return [item for item in cms if isinstance(item, dict)]
    if isinstance(cms, dict):
        rows = cms.get("list") or cms.get("data") or []
        if isinstance(rows, list):
            return [item for item in rows if isinstance(item, dict)]
    return []


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
