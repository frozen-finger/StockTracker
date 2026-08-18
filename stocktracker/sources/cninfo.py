from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from stocktracker.extract import extract_pdf_text
from stocktracker.http import HttpClient
from stocktracker.keywords import CNINFO_SEARCH_TERMS, CNINFO_TERM_EVENTS, classify_text, evidence_snippets
from stocktracker.models import Document

LOG = logging.getLogger(__name__)
CNINFO_QUERY_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_DOWNLOAD_BASE = "https://static.cninfo.com.cn/"
CHINA_TZ = ZoneInfo("Asia/Shanghai")


class CninfoCollector:
    name = "cninfo"

    def __init__(self, http: HttpClient, page_size: int = 30, max_pages: int = 20) -> None:
        self.http = http
        self.page_size = page_size
        self.max_pages = max_pages
        self.warnings: list[str] = []

    def collect(self, start: date, end: date) -> list[Document]:
        self.warnings = []
        documents: dict[str, Document] = {}
        successful_queries = 0
        for term in CNINFO_SEARCH_TERMS:
            for column in ("szse", "sse", "bse"):
                try:
                    for item in self._query(term, column, start, end):
                        document = self._from_item(item)
                        document.matched_events = list(
                            dict.fromkeys([*document.matched_events, CNINFO_TERM_EVENTS[term]])
                        )
                        document.matched_keywords = list(dict.fromkeys([*document.matched_keywords, term]))
                        existing = documents.get(document.id)
                        if existing is None:
                            documents[document.id] = document
                        else:
                            existing.matched_events = list(
                                dict.fromkeys([*existing.matched_events, *document.matched_events])
                            )
                            existing.matched_keywords = list(
                                dict.fromkeys([*existing.matched_keywords, *document.matched_keywords])
                            )
                    successful_queries += 1
                except Exception as error:
                    message = f"query term={term!r} column={column} failed: {type(error).__name__}: {error}"
                    self.warnings.append(message)
                    LOG.warning(message)

        if successful_queries == 0:
            raise RuntimeError("all CNInfo queries failed")

        for document in documents.values():
            if "equity_change_report" in document.matched_events:
                self._enrich_pdf(document)
            else:
                terms = "、".join(document.matched_keywords)
                document.evidence_snippets = [f"巨潮全文检索命中：{terms}；公告标题：{document.title}"]
                document.content_status = "fulltext_search_matched"
        return list(documents.values())

    def _query(self, term: str, column: str, start: date, end: date):
        for page in range(1, self.max_pages + 1):
            data = {
                "pageNum": str(page),
                "pageSize": str(self.page_size),
                "column": column,
                "tabName": "fulltext",
                "plate": "",
                "stock": "",
                "searchkey": term,
                "secid": "",
                "category": "",
                "trade": "",
                "seDate": f"{start:%Y-%m-%d}~{end:%Y-%m-%d}",
                "sortName": "time",
                "sortType": "desc",
                "isHLtitle": "true",
            }
            response = self.http.request(
                "POST",
                CNINFO_QUERY_URL,
                data=data,
                headers={
                    "Origin": "https://www.cninfo.com.cn",
                    "Referer": "https://www.cninfo.com.cn/new/fulltextSearch",
                    "X-Requested-With": "XMLHttpRequest",
                },
            )
            payload = response.json()
            announcements = payload.get("announcements") or []
            yield from announcements
            if not payload.get("hasMore") or not announcements:
                break

    def _from_item(self, item: dict) -> Document:
        title = (item.get("announcementTitle") or "").replace("<em>", "").replace("</em>", "")
        adjunct_url = item.get("adjunctUrl") or ""
        url = CNINFO_DOWNLOAD_BASE + adjunct_url.lstrip("/")
        timestamp = int(item.get("announcementTime") or 0) / 1000
        published_at = datetime.fromtimestamp(timestamp, CHINA_TZ)
        identity = str(item.get("announcementId") or hashlib.sha256(url.encode()).hexdigest()[:24])
        events, keywords = classify_text(title)
        return Document(
            id=f"cninfo:{identity}",
            source_type="official",
            source_name="巨潮资讯",
            title=title,
            url=url,
            published_at=published_at,
            company=item.get("secName"),
            stock_code=item.get("secCode"),
            matched_events=events,
            matched_keywords=keywords,
        )

    def _enrich_pdf(self, document: Document) -> None:
        try:
            response = self.http.request("GET", document.url)
            text = extract_pdf_text(response.content)
            events, keywords = classify_text(f"{document.title}\n{text}")
            document.matched_events = list(dict.fromkeys([*document.matched_events, *events]))
            document.matched_keywords = list(dict.fromkeys([*document.matched_keywords, *keywords]))
            document.evidence_snippets = evidence_snippets(text, keywords)
            if not document.evidence_snippets:
                terms = "、".join(document.matched_keywords)
                document.evidence_snippets = [f"巨潮全文检索命中：{terms}；公告标题：{document.title}"]
            document.content_status = "extracted" if text else "empty_pdf_text"
        except Exception as error:  # A single malformed PDF must not abort the weekly run.
            document.content_status = "extract_failed"
            terms = "、".join(document.matched_keywords)
            document.evidence_snippets = [f"巨潮全文检索命中：{terms}；公告标题：{document.title}"]
            LOG.warning("Failed to extract %s: %s", document.url, error)
