from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import date, datetime
from typing import Any, Iterable
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from stocktracker.extract import extract_pdf_text
from stocktracker.http import HttpClient
from stocktracker.keywords import CNINFO_SEARCH_TERMS, CNINFO_TERM_EVENTS, classify_text, evidence_snippets
from stocktracker.models import Document
from stocktracker.sources.cninfo import CninfoCollector

LOG = logging.getLogger(__name__)
CHINA_TZ = ZoneInfo("Asia/Shanghai")

SSE_QUERY_URL = "https://query.sse.com.cn/security/stock/queryCompanyBulletinNew.do"
SSE_REFERER = "https://www.sse.com.cn/disclosure/listedinfo/announcement/"
SZSE_QUERY_URL = "https://www.szse.cn/api/disc/announcement/annList"
SZSE_REFERER = "https://www.szse.cn/disclosure/listed/notice/index.html"
BSE_QUERY_URL = "https://www.bse.cn/disclosureInfoController/companyAnnouncement.do"
BSE_REFERER = "https://www.bse.cn/disclosure/announcement.html"


class FallbackAwareCninfoCollector(CninfoCollector):
    """CNInfo collector that exposes whether the primary source hard-failed."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.failed = False

    def collect(self, start: date, end: date) -> list[Document]:
        self.failed = False
        try:
            return super().collect(start, end)
        except Exception:
            self.failed = True
            raise


class ExchangeFallbackCollector:
    name = "exchange_fallback"

    def __init__(
        self,
        http: HttpClient,
        primary: Any,
        collectors: Iterable[Any] | None = None,
    ) -> None:
        self.primary = primary
        configured = list(collectors) if collectors is not None else [
            SseAnnouncementCollector(http),
            SzseAnnouncementCollector(http),
            BseAnnouncementCollector(http),
        ]
        self.collectors = {collector.name: collector for collector in configured}
        self.warnings: list[str] = []
        self.recovered_queries: set[tuple[str, str]] = set()
        self.unrecovered_queries: set[tuple[str, str]] = set()
        self.resolved_warnings: dict[str, set[str]] = {}

    def collect(self, start: date, end: date) -> list[Document]:
        self.warnings = []
        self.recovered_queries = set()
        self.resolved_warnings = {}
        failed_queries = set(getattr(self.primary, "failed_queries", set()))
        self.unrecovered_queries = set(failed_queries)
        if not failed_queries:
            return []

        targets: dict[str, set[str]] = {}
        for term, column in failed_queries:
            targets.setdefault(column, set()).add(term)

        documents: dict[str, Document] = {}
        attempted_sources = 0
        successful_sources = 0
        for column, terms in sorted(targets.items()):
            collector = self.collectors.get(column)
            if collector is None:
                message = f"no fallback collector configured for CNInfo column={column}"
                self.warnings.append(message)
                LOG.warning(message)
                continue

            attempted_sources += 1
            try:
                collected = collector.collect_terms(sorted(terms), start, end)
                successful_sources += 1
                for warning in collector.warnings:
                    self.warnings.append(f"{collector.name}: {warning}")
                for document in collected:
                    documents[document.id] = document
                failed_terms = set(getattr(collector, "failed_terms", set()))
                for term in terms:
                    key = (term, column)
                    if term not in failed_terms:
                        self.recovered_queries.add(key)
            except Exception as error:
                message = f"{collector.name} failed: {type(error).__name__}: {error}"
                self.warnings.append(message)
                LOG.warning(message)

        if attempted_sources and successful_sources == 0:
            raise RuntimeError("all targeted exchange fallback sources failed")

        self.unrecovered_queries = failed_queries - self.recovered_queries
        recovered_messages = {
            message
            for key, message in getattr(self.primary, "failed_query_errors", {}).items()
            if key in self.recovered_queries
        }
        if getattr(self.primary, "failed", False) and not self.unrecovered_queries:
            recovered_messages.add("RuntimeError: all CNInfo queries failed")
        if recovered_messages:
            self.resolved_warnings[self.primary.name] = recovered_messages

        if self.recovered_queries:
            LOG.info(
                "Exchange fallback recovered %s/%s failed CNInfo queries",
                len(self.recovered_queries),
                len(failed_queries),
            )
        return list(documents.values())


class _BaseExchangeCollector:
    name = ""
    source_name = ""

    def __init__(self, http: HttpClient, page_size: int = 50, max_pages: int = 100) -> None:
        self.http = http
        self.page_size = page_size
        self.max_pages = max_pages
        self.warnings: list[str] = []
        self.failed_terms: set[str] = set()

    def collect(self, start: date, end: date) -> list[Document]:
        return self.collect_terms(CNINFO_SEARCH_TERMS, start, end)

    def collect_terms(self, terms: Iterable[str], start: date, end: date) -> list[Document]:
        raise NotImplementedError

    def _document(
        self,
        *,
        identity: str,
        title: str,
        url: str,
        published_at: datetime,
        company: str | None,
        stock_code: str | None,
        matched_term: str,
    ) -> Document:
        events, keywords = classify_text(title)
        expected_event = CNINFO_TERM_EVENTS.get(matched_term)
        if expected_event and expected_event not in events:
            events.append(expected_event)
        if matched_term not in keywords:
            keywords.append(matched_term)
        document = Document(
            id=f"{self.name}:{identity}",
            source_type="official",
            source_name=self.source_name,
            title=title,
            url=url,
            published_at=published_at,
            company=company,
            stock_code=stock_code,
            matched_events=list(dict.fromkeys(events)),
            matched_keywords=list(dict.fromkeys(keywords)),
            evidence_snippets=[f"{self.source_name}公告检索命中：{matched_term}；公告标题：{title}"],
            content_status="exchange_search_matched",
        )
        if "equity_change_report" in document.matched_events and document.url:
            self._enrich_pdf(document)
        return document

    def _enrich_pdf(self, document: Document) -> None:
        try:
            response = self.http.request("GET", document.url)
            text = extract_pdf_text(response.content)
            events, keywords = classify_text(f"{document.title}\n{text}")
            document.matched_events = list(dict.fromkeys([*document.matched_events, *events]))
            document.matched_keywords = list(dict.fromkeys([*document.matched_keywords, *keywords]))
            snippets = evidence_snippets(text, document.matched_keywords)
            if snippets:
                document.evidence_snippets = snippets
            document.content_status = "extracted" if text else "empty_pdf_text"
        except Exception as error:
            LOG.warning("Failed to extract exchange PDF %s: %s", document.url, error)
            document.content_status = "extract_failed"

    def _warn_truncated(self, term: str) -> None:
        message = f"query term={term!r} truncated after {self.max_pages} pages"
        self.warnings.append(message)
        self.failed_terms.add(term)
        LOG.warning("%s: %s", self.name, message)


class SseAnnouncementCollector(_BaseExchangeCollector):
    name = "sse"
    source_name = "上海证券交易所"

    def collect_terms(self, terms: Iterable[str], start: date, end: date) -> list[Document]:
        self.warnings = []
        self.failed_terms = set()
        documents: dict[str, Document] = {}
        successful_calls = 0
        term_list = list(dict.fromkeys(terms))
        for term in term_list:
            successful_stock_types = 0
            for stock_type in ("1", "8"):
                try:
                    for item in self._query(term, stock_type, start, end):
                        document = self._from_item(item, term)
                        documents[document.id] = document
                    successful_calls += 1
                    successful_stock_types += 1
                except Exception as error:
                    message = f"query term={term!r} stock_type={stock_type} failed: {type(error).__name__}: {error}"
                    self.warnings.append(message)
                    LOG.warning("%s: %s", self.name, message)
            if successful_stock_types < 2:
                self.failed_terms.add(term)
        if term_list and successful_calls == 0:
            raise RuntimeError("all targeted SSE queries failed")
        return list(documents.values())

    def _query(self, term: str, stock_type: str, start: date, end: date):
        page = 1
        while True:
            response = self.http.request(
                "GET",
                SSE_QUERY_URL,
                params={
                    "jsonCallBack": "jsonp",
                    "isPagination": "true",
                    "pageHelp.pageSize": self.page_size,
                    "pageHelp.pageNo": page,
                    "pageHelp.beginPage": page,
                    "pageHelp.cacheSize": 1,
                    "START_DATE": start.isoformat(),
                    "END_DATE": end.isoformat(),
                    "SECURITY_CODE": "",
                    "TITLE": term,
                    "stockType": stock_type,
                },
                headers={"Referer": SSE_REFERER},
            )
            payload = _parse_json_or_jsonp(response.text)
            page_help = payload.get("pageHelp") if isinstance(payload, dict) else None
            if not isinstance(page_help, dict):
                break
            data = page_help.get("data") or []
            rows = _flatten_dict_rows(data)
            yield from rows
            page_count = int(page_help.get("pageCount") or 0)
            if page_count == 0 or page >= page_count:
                break
            if page >= self.max_pages:
                self._warn_truncated(term)
                break
            page += 1

    def _from_item(self, item: dict[str, Any], term: str) -> Document:
        raw_url = str(item.get("URL") or "").strip()
        if raw_url.startswith("/disclosure/"):
            url = urljoin("https://static.sse.com.cn", raw_url)
        else:
            url = urljoin("https://static.sse.com.cn/disclosure/", raw_url.lstrip("/"))
        title = str(item.get("TITLE") or "").strip()
        published_at = _parse_exchange_datetime(item.get("SSEDATE"))
        identity = str(item.get("ORG_BULLETIN_ID") or hashlib.sha256(url.encode()).hexdigest()[:24])
        return self._document(
            identity=identity,
            title=title,
            url=url,
            published_at=published_at,
            company=_clean_optional(item.get("SECURITY_NAME")),
            stock_code=_clean_optional(item.get("SECURITY_CODE")),
            matched_term=term,
        )


class SzseAnnouncementCollector(_BaseExchangeCollector):
    name = "szse"
    source_name = "深圳证券交易所"

    def collect_terms(self, terms: Iterable[str], start: date, end: date) -> list[Document]:
        self.warnings = []
        self.failed_terms = set()
        documents: dict[str, Document] = {}
        successful_calls = 0
        term_list = list(dict.fromkeys(terms))
        for term in term_list:
            try:
                for item in self._query(term, start, end):
                    document = self._from_item(item, term)
                    documents[document.id] = document
                successful_calls += 1
            except Exception as error:
                self.failed_terms.add(term)
                message = f"query term={term!r} failed: {type(error).__name__}: {error}"
                self.warnings.append(message)
                LOG.warning("%s: %s", self.name, message)
        if term_list and successful_calls == 0:
            raise RuntimeError("all targeted SZSE queries failed")
        return list(documents.values())

    def _query(self, term: str, start: date, end: date):
        page = 1
        while True:
            response = self.http.request(
                "POST",
                SZSE_QUERY_URL,
                json={
                    "seDate": [start.isoformat(), end.isoformat()],
                    "searchKey": [term],
                    "channelCode": ["listedNotice_disc"],
                    "pageSize": self.page_size,
                    "pageNum": page,
                },
                headers={
                    "Origin": "https://www.szse.cn",
                    "Referer": SZSE_REFERER,
                    "Content-Type": "application/json",
                    "X-Request-Type": "ajax",
                    "X-Requested-With": "XMLHttpRequest",
                },
            )
            payload = response.json()
            rows = payload.get("data") or []
            yield from [item for item in rows if isinstance(item, dict)]
            total = int(payload.get("announceCount") or 0)
            if not rows or page * self.page_size >= total:
                break
            if page >= self.max_pages:
                self._warn_truncated(term)
                break
            page += 1

    def _from_item(self, item: dict[str, Any], term: str) -> Document:
        title = str(item.get("title") or "").strip()
        attach_path = str(item.get("attachPath") or "").strip()
        url = urljoin("https://disc.static.szse.cn/download/", attach_path.lstrip("/"))
        codes = item.get("secCode") or []
        names = item.get("secName") or []
        stock_code = str(codes[0]).strip() if isinstance(codes, list) and codes else None
        company = str(names[0]).strip() if isinstance(names, list) and names else None
        identity = str(item.get("annId") or item.get("id") or hashlib.sha256(url.encode()).hexdigest()[:24])
        return self._document(
            identity=identity,
            title=title,
            url=url,
            published_at=_parse_exchange_datetime(item.get("publishTime")),
            company=company,
            stock_code=stock_code,
            matched_term=term,
        )


class BseAnnouncementCollector(_BaseExchangeCollector):
    name = "bse"
    source_name = "北京证券交易所"

    NEED_FIELDS = (
        "companyCd",
        "companyName",
        "disclosureTitle",
        "disclosurePostTitle",
        "destFilePath",
        "publishDate",
        "xxfcbj",
        "fileExt",
        "xxzrlx",
        "disclosureType",
        "disclosureSubType",
    )

    def collect_terms(self, terms: Iterable[str], start: date, end: date) -> list[Document]:
        self.warnings = []
        self.failed_terms = set()
        self.http.request("GET", BSE_REFERER, headers={"Referer": "https://www.bse.cn/"})
        documents: dict[str, Document] = {}
        successful_calls = 0
        term_list = list(dict.fromkeys(terms))
        for term in term_list:
            try:
                for item in self._query(term, start, end):
                    document = self._from_item(item, term)
                    documents[document.id] = document
                successful_calls += 1
            except Exception as error:
                self.failed_terms.add(term)
                message = f"query term={term!r} failed: {type(error).__name__}: {error}"
                self.warnings.append(message)
                LOG.warning("%s: %s", self.name, message)
        if term_list and successful_calls == 0:
            raise RuntimeError("all targeted BSE queries failed")
        return list(documents.values())

    def _query(self, term: str, start: date, end: date):
        page = 0
        while True:
            form: list[tuple[str, str]] = [
                ("disclosureType[]", "5"),
                ("disclosureSubtype[]", ""),
                ("page", str(page)),
                ("companyCd", ""),
                ("isNewThree", "1"),
                ("startTime", start.isoformat()),
                ("endTime", end.isoformat()),
                ("keyword", term),
                ("xxfcbj[]", "2"),
                ("sortfield", "xxssdq"),
                ("sorttype", "asc"),
            ]
            form.extend(("needFields[]", field) for field in self.NEED_FIELDS)
            response = self.http.request(
                "POST",
                BSE_QUERY_URL,
                data=form,
                headers={
                    "Origin": "https://www.bse.cn",
                    "Referer": BSE_REFERER,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            payload = _parse_json_or_jsonp(response.text)
            if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
                break
            list_info = payload[0].get("listInfo") or {}
            rows = list_info.get("content") or []
            yield from [item for item in rows if isinstance(item, dict)]
            total_pages = int(list_info.get("totalPages") or 0)
            if total_pages == 0 or page + 1 >= total_pages:
                break
            if page + 1 >= self.max_pages:
                self._warn_truncated(term)
                break
            page += 1

    def _from_item(self, item: dict[str, Any], term: str) -> Document:
        title = f"{item.get('disclosureTitle') or ''}{item.get('disclosurePostTitle') or ''}".strip()
        raw_url = str(item.get("destFilePath") or "").strip()
        url = urljoin("https://www.bse.cn/", raw_url.lstrip("/"))
        code = _clean_optional(item.get("companyCd"))
        published_at = _parse_exchange_datetime(item.get("publishDate"))
        identity_seed = f"{code}|{published_at.date().isoformat()}|{title}"
        identity = hashlib.sha256(identity_seed.encode()).hexdigest()[:24]
        return self._document(
            identity=identity,
            title=title,
            url=url,
            published_at=published_at,
            company=_clean_optional(item.get("companyName")),
            stock_code=code,
            matched_term=term,
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


def _flatten_dict_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            rows.append(item)
        elif isinstance(item, list):
            rows.extend(child for child in item if isinstance(child, dict))
    return rows


def _parse_exchange_datetime(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime.now(CHINA_TZ)
    normalized = text.replace("/", "-")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        parsed = datetime.strptime(normalized[:10], "%Y-%m-%d")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=CHINA_TZ)
    return parsed.astimezone(CHINA_TZ)


def _clean_optional(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
