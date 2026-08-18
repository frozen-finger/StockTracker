from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, time
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, quote_plus, urlparse
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from stocktracker.http import HttpClient
from stocktracker.keywords import NEWS_SEARCH_TERMS, classify_text, evidence_snippets
from stocktracker.models import Document

LOG = logging.getLogger(__name__)
CHINA_TZ = ZoneInfo("Asia/Shanghai")


class BingNewsCollector:
    name = "bing_news"

    def __init__(self, http: HttpClient) -> None:
        self.http = http
        self.warnings: list[str] = []

    def collect(self, start: date, end: date) -> list[Document]:
        self.warnings = []
        documents: dict[str, Document] = {}
        successful_queries = 0
        for term in NEWS_SEARCH_TERMS:
            try:
                url = f"https://www.bing.com/news/search?q={quote_plus(term)}&format=rss&setlang=zh-cn"
                response = self.http.request("GET", url)
                root = ElementTree.fromstring(response.content)
                for item in root.findall("./channel/item"):
                    document = self._from_item(item)
                    local_date = document.published_at.astimezone(CHINA_TZ).date()
                    if start <= local_date <= end and document.matched_events:
                        documents.setdefault(document.id, document)
                successful_queries += 1
            except Exception as error:
                message = f"query term={term!r} failed: {type(error).__name__}: {error}"
                self.warnings.append(message)
                LOG.warning(message)
        if successful_queries == 0:
            raise RuntimeError("all Bing News queries failed")
        return list(documents.values())

    def _from_item(self, item: ElementTree.Element) -> Document:
        title = item.findtext("title", default="").strip()
        description_html = item.findtext("description", default="")
        description = BeautifulSoup(description_html, "html.parser").get_text(" ", strip=True)
        raw_url = item.findtext("link", default="").strip()
        url = _unwrap_bing_url(raw_url)
        published = item.findtext("pubDate", default="")
        try:
            published_at = parsedate_to_datetime(published)
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=CHINA_TZ)
        except (TypeError, ValueError):
            published_at = datetime.combine(date.today(), time.min, CHINA_TZ)
        events, keywords = classify_text(f"{title}\n{description}")
        identity = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
        return Document(
            id=f"news:{identity}",
            source_type="news",
            source_name=item.findtext("source", default="").strip() or "Bing News RSS",
            title=title,
            url=url,
            published_at=published_at.astimezone(CHINA_TZ),
            matched_events=events,
            matched_keywords=keywords,
            evidence_snippets=evidence_snippets(description, keywords),
            content_status="rss_summary",
        )


def _unwrap_bing_url(url: str) -> str:
    query = parse_qs(urlparse(url).query)
    return query.get("url", [url])[0]
