from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from stocktracker.http import HttpClient
from stocktracker.keywords import classify_news_text, evidence_snippets
from stocktracker.models import Document

LOG = logging.getLogger(__name__)
CHINA_TZ = ZoneInfo("Asia/Shanghai")
SINA_ROLL_URL = "https://feed.mix.sina.com.cn/api/roll/get"


class SinaFinanceNewsCollector:
    """Collect governance coverage from Sina's stock/finance rolling feeds."""

    name = "sina_news"

    def __init__(self, http: HttpClient, page_size: int = 50, max_pages: int = 12) -> None:
        if page_size < 1 or page_size > 50:
            raise ValueError("page_size must be between 1 and 50")
        if max_pages < 1:
            raise ValueError("max_pages must be positive")
        self.http = http
        self.page_size = page_size
        self.max_pages = max_pages
        self.warnings: list[str] = []

    def collect(self, start: date, end: date) -> list[Document]:
        self.warnings = []
        documents: dict[str, Document] = {}
        successful_channels = 0
        scanned = 0

        # 2517: 股票, 2516: 财经. Keyword search on this endpoint is not
        # consistently populated, so scan the rolling feeds with k="" and apply
        # the governance classifier locally. Stop once a page reaches older news.
        for lid in (2517, 2516):
            try:
                channel_scanned, channel_documents = self._collect_channel(lid, start, end)
                scanned += channel_scanned
                for document in channel_documents:
                    documents.setdefault(document.id, document)
                successful_channels += 1
            except Exception as error:
                message = f"feed lid={lid} failed: {type(error).__name__}: {error}"
                self.warnings.append(message)
                LOG.warning("sina news: %s", message)

        if successful_channels == 0:
            raise RuntimeError("all Sina Finance rolling feeds failed")
        LOG.info(
            "Sina news scanned %s rolling items and retained %s governance stories",
            scanned,
            len(documents),
        )
        return list(documents.values())

    def _collect_channel(self, lid: int, start: date, end: date) -> tuple[int, list[Document]]:
        documents: dict[str, Document] = {}
        scanned = 0
        for page in range(1, self.max_pages + 1):
            rows = self._query_page(lid, page)
            if not rows:
                break
            scanned += len(rows)
            reached_older = False
            for item in rows:
                try:
                    document = self._from_item(item)
                except ValueError:
                    continue
                local_date = document.published_at.astimezone(CHINA_TZ).date()
                if local_date < start:
                    reached_older = True
                    continue
                if local_date > end:
                    continue
                if document.matched_events:
                    documents.setdefault(document.id, document)
            if len(rows) < self.page_size or reached_older:
                break
        return scanned, list(documents.values())

    def _query_page(self, lid: int, page: int) -> list[dict[str, Any]]:
        response = self.http.request(
            "GET",
            SINA_ROLL_URL,
            params={
                "pageid": 153,
                "lid": lid,
                "k": "",
                "num": self.page_size,
                "page": page,
            },
            headers={"Referer": "https://finance.sina.com.cn/"},
        )
        payload = response.json()
        result = payload.get("result") if isinstance(payload, dict) else None
        rows = result.get("data") if isinstance(result, dict) else None
        if not isinstance(rows, list):
            return []
        return [item for item in rows if isinstance(item, dict)]

    def _from_item(self, item: dict[str, Any]) -> Document:
        title = _clean_html(item.get("title"))
        summary = _clean_html(item.get("intro") or item.get("summary") or item.get("keywords"))
        keywords_field = _clean_html(item.get("keywords"))
        url = str(item.get("url") or "").strip()
        published_at = _parse_ctime(item.get("ctime"))
        events, keywords = classify_news_text(f"{title}\n{summary}\n{keywords_field}")
        identity_seed = url or str(item.get("docid") or f"{title}|{published_at.isoformat()}")
        identity = hashlib.sha256(identity_seed.encode("utf-8")).hexdigest()[:24]
        source_name = (
            str(item.get("media_name") or item.get("media") or item.get("source") or "新浪财经").strip()
            or "新浪财经"
        )
        evidence_text = summary or keywords_field or title
        return Document(
            id=f"news:{identity}",
            source_type="news",
            source_name=source_name,
            title=title,
            url=url,
            published_at=published_at,
            matched_events=events,
            matched_keywords=keywords,
            evidence_snippets=evidence_snippets(evidence_text, keywords),
            content_status="sina_roll_summary",
        )


def _clean_html(value: Any) -> str:
    return BeautifulSoup(str(value or ""), "html.parser").get_text(" ", strip=True)


def _parse_ctime(value: Any) -> datetime:
    try:
        timestamp = int(str(value or "0"))
    except ValueError as error:
        raise ValueError(f"unsupported Sina ctime: {value!r}") from error
    if timestamp <= 0:
        raise ValueError(f"unsupported Sina ctime: {value!r}")
    return datetime.fromtimestamp(timestamp, CHINA_TZ)
