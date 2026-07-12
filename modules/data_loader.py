"""Load, clean, and persist public competitor intelligence records."""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

import feedparser
import pandas as pd
import requests
from bs4 import BeautifulSoup
from langchain_core.documents import Document

RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed")


@dataclass
class IntelligenceRecord:
    title: str
    content: str
    source_url: str
    source_type: str = "manual"
    competitor: str = ""
    dimension: str = "general"
    collected_at: str = ""
    record_id: str = ""
    source_name: str = ""
    published_at: str = ""

    def __post_init__(self) -> None:
        self.source_url = normalize_source_url(self.source_url)
        self.content = clean_text(self.content)
        self.title = clean_text(self.title)
        if not self.collected_at:
            self.collected_at = datetime.now(timezone.utc).isoformat()
        if not self.record_id:
            base = f"{self.source_url}|{self.title}|{self.content[:200]}"
            self.record_id = hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]


def normalize_source_url(url: str) -> str:
    """Normalize source identity while preserving non-tracking query parameters."""
    value = (url or "").strip()
    if not value:
        return ""
    parsed = urlsplit(value)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    port = parsed.port
    netloc = host
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    path = re.sub(r"/+", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    tracking_keys = {"fbclid", "gclid", "mc_cid", "mc_eid"}
    query_items = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in tracking_keys
    ]
    return urlunsplit((scheme, netloc, path, urlencode(sorted(query_items)), ""))


def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    ad_patterns = ["点击查看", "责任编辑", "广告", "免责声明"]
    for pattern in ad_patterns:
        text = text.replace(pattern, "")
    return text.strip()


def dedupe_records(records: Iterable[IntelligenceRecord]) -> list[IntelligenceRecord]:
    seen: set[str] = set()
    unique: list[IntelligenceRecord] = []
    for record in records:
        if record.record_id in seen or not record.content:
            continue
        seen.add(record.record_id)
        unique.append(record)
    return unique


def load_csv(path: str | Path) -> list[IntelligenceRecord]:
    csv_path = Path(path)
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return []
    df = pd.read_csv(csv_path)
    records = []
    for row in df.fillna("").to_dict(orient="records"):
        fresh_content = build_content_from_fresh_row(row)
        records.append(
            IntelligenceRecord(
                title=row.get("title", "") or build_title_from_row(row),
                content=row.get("content", row.get("text", fresh_content)),
                source_url=row.get("source_url", row.get("url", "")),
                source_type=row.get("source_type", "csv"),
                competitor=row.get("competitor", "") or build_competitor_from_row(row),
                dimension=row.get("dimension", "") or infer_dimension_from_row(row),
                collected_at=row.get("collected_at", row.get("publish_time", row.get("quote_date", ""))),
                record_id=row.get("record_id", ""),
                source_name=row.get("source_name", row.get("source", "")),
                published_at=row.get("published_at", row.get("publish_time", "")),
            )
        )
    return dedupe_records(records)


def build_content_from_fresh_row(row: dict[str, Any]) -> str:
    if {"quote_date", "province", "market", "vegetable_name", "current_price"}.issubset(row):
        parts = [
            f"报价日期：{row.get('quote_date', '')}",
            f"省份：{row.get('province', '')}",
            f"市场：{row.get('market', '')}",
            f"菜品：{row.get('vegetable_name', '')}",
            f"商品编码：{row.get('commodity_id', '')}",
            f"当前价格：{row.get('current_price', '')}{row.get('unit', '')}",
            f"上一期价格：{row.get('previous_price', '')}{row.get('unit', '')}",
            f"涨跌幅：{row.get('change_rate', '')}%",
            f"来源链接：{row.get('source_url', row.get('url', ''))}",
        ]
        return "；".join(str(part) for part in parts if str(part).strip())

    if "product_name" not in row:
        return ""
    parts = [
        f"区域供应源竞品：{row.get('competitor', '')}",
        f"商品类别：{row.get('product_category', '')}",
        f"商品名称：{row.get('product_name', '')}",
        f"规格：{row.get('specification', '')}",
        f"价格：{row.get('price', '')}",
        f"单位价格：{row.get('unit_price', '')}",
        f"信息标题：{row.get('title', '')}",
        f"内容：{row.get('content', '')}",
        f"来源：{row.get('source', '')}",
        f"发布时间：{row.get('publish_time', '')}",
    ]
    return "；".join(str(part) for part in parts if str(part).strip())


def build_title_from_row(row: dict[str, Any]) -> str:
    if {"quote_date", "province", "market", "vegetable_name"}.issubset(row):
        return (
            f"{row.get('quote_date', '')} "
            f"{row.get('province', '')}"
            f"{row.get('market', '')}"
            f"{row.get('vegetable_name', '')}价格行情"
        ).strip()
    return ""


def build_competitor_from_row(row: dict[str, Any]) -> str:
    if {"province", "vegetable_name"}.issubset(row):
        return f"{row.get('province', '')}{row.get('vegetable_name', '')}".strip()
    return ""


def infer_dimension_from_row(row: dict[str, Any]) -> str:
    if {"current_price", "previous_price", "change_rate"}.issubset(row):
        return "price"
    return "general"


def is_public_source_url(url: str) -> bool:
    """Return whether a URL can identify a public, non-demo source."""
    parsed = urlparse((url or "").strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not host:
        return False
    if host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local") or host.endswith(".test"):
        return False
    return host not in {"example.com", "www.example.com", "example.org", "www.example.org", "example.net", "www.example.net"}


def parse_agri_daily_html(
    html: str,
    source_url: str,
    collected_at: str = "",
) -> IntelligenceRecord:
    """Parse one Agriculture Ministry daily wholesale-price report."""
    if not is_public_source_url(source_url):
        raise ValueError("Agriculture daily report requires a public HTTP(S) source URL")
    soup = BeautifulSoup(html, "html.parser")
    title_node = soup.select_one("h1")
    title = clean_text(title_node.get_text(" ", strip=True) if title_node else (soup.title.string if soup.title else ""))
    content_node = soup.select_one("div.TRS_Editor")
    if not content_node:
        raise ValueError("Agriculture daily report content was not found")
    content = clean_text(content_node.get_text(" ", strip=True))
    if not title or not content:
        raise ValueError("Agriculture daily report is missing title or content")
    source_meta = soup.select_one('meta[name="source"]')
    source_name = clean_text(source_meta.get("content", "") if source_meta else "") or "农业农村部市场与信息化司"
    page_text = clean_text(soup.get_text(" ", strip=True))
    published_match = re.search(r"时间[：:]\s*(\d{4}-\d{2}-\d{2})", page_text)
    if not published_match:
        published_match = re.search(r"/(\d{8})/t\d+_", source_url)
        published_at = datetime.strptime(published_match.group(1), "%Y%m%d").date().isoformat() if published_match else ""
    else:
        published_at = published_match.group(1)
    if not published_at:
        raise ValueError("Agriculture daily report publication date was not found")
    return IntelligenceRecord(
        title=title,
        content=content,
        source_url=source_url,
        source_type="agri_daily",
        competitor="全国农产品批发市场",
        dimension="price",
        collected_at=collected_at,
        source_name=source_name,
        published_at=published_at,
    )


def fetch_agri_daily_reports(
    urls: list[str],
    fetcher=requests.get,
    on_error=None,
) -> list[IntelligenceRecord]:
    """Fetch a small configured batch of public daily reports with retries."""
    records: list[IntelligenceRecord] = []
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        )
    }
    errors: list[dict[str, str]] = []
    for index, url in enumerate(urls):
        if not is_public_source_url(url):
            raise ValueError(f"Non-public source URL is not allowed in real collection: {url}")
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = fetcher(url, timeout=20, headers=headers)
                response.raise_for_status()
                if getattr(response, "apparent_encoding", None):
                    response.encoding = response.apparent_encoding
                records.append(parse_agri_daily_html(response.text, url))
                break
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(1)
        else:
            error = {"url": url, "error": str(last_error)}
            errors.append(error)
            if on_error:
                on_error(error)
        if fetcher is requests.get and index < len(urls) - 1:
            time.sleep(2)
    if not records and errors:
        raise RuntimeError(f"All Agriculture daily reports failed: {errors}")
    return dedupe_records(records)


def fetch_webpage(url: str, competitor: str = "", dimension: str = "general") -> IntelligenceRecord:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        )
    }
    last_error: Exception | None = None
    for _ in range(3):
        try:
            response = requests.get(url, timeout=20, headers=headers)
            break
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(1)
    else:
        raise RuntimeError(f"Failed to fetch webpage after retries: {last_error}") from last_error
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else url
    content = soup.get_text(" ", strip=True)
    return IntelligenceRecord(
        title=title,
        content=content[:12000],
        source_url=url,
        source_type="webpage",
        competitor=competitor,
        dimension=dimension,
    )


def fetch_rss(url: str, competitor: str = "", dimension: str = "general", limit: int = 20) -> list[IntelligenceRecord]:
    feed = feedparser.parse(url)
    records = []
    for entry in feed.entries[:limit]:
        content = entry.get("summary", "") or entry.get("description", "")
        records.append(
            IntelligenceRecord(
                title=entry.get("title", ""),
                content=BeautifulSoup(content, "html.parser").get_text(" ", strip=True),
                source_url=entry.get("link", url),
                source_type="rss",
                competitor=competitor,
                dimension=dimension,
            )
        )
    return dedupe_records(records)


def fetch_search_page(
    url: str,
    competitor: str = "",
    dimension: str = "general",
    limit: int = 20,
) -> list[IntelligenceRecord]:
    response = requests.get(
        url,
        timeout=20,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            )
        },
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    records = []
    for link in soup.find_all("a", href=True):
        title = clean_text(link.get_text(" ", strip=True))
        href = link["href"]
        if not title or href.startswith("#") or href.startswith("javascript:"):
            continue
        if href.startswith("/"):
            from urllib.parse import urljoin

            href = urljoin(url, href)
        parent_text = clean_text(link.parent.get_text(" ", strip=True) if link.parent else title)
        records.append(
            IntelligenceRecord(
                title=title[:200],
                content=parent_text[:2000] or title,
                source_url=href,
                source_type="search_page",
                competitor=competitor,
                dimension=dimension,
            )
        )
        if len(records) >= limit:
            break
    return dedupe_records(records)


def save_records_csv(records: Iterable[IntelligenceRecord], path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    unique = dedupe_records(records)
    columns = [
        "title",
        "content",
        "source_url",
        "source_type",
        "competitor",
        "dimension",
        "collected_at",
        "record_id",
        "source_name",
        "published_at",
    ]
    pd.DataFrame([asdict(record) for record in unique], columns=columns).to_csv(
        output_path,
        index=False,
        encoding="utf-8-sig",
    )
    return output_path


def load_project_records() -> list[IntelligenceRecord]:
    """Load only cleaned, traceable records for the formal knowledge base."""
    path = PROCESSED_DIR / "intelligence_records.csv"
    if not path.exists():
        return []
    return dedupe_records(
        record
        for record in load_csv(path)
        if is_public_source_url(record.source_url) and record.source_name and record.published_at
    )


class MultiSourceDocumentLoader:
    """LangChain-style loader for CSV, RSS, webpage, and forum sources."""

    def __init__(
        self,
        source_type: str,
        url: str = "",
        path: str = "",
        competitor: str = "",
        dimension: str = "general",
        urls: list[str] | None = None,
    ):
        self.source_type = source_type
        self.url = url
        self.path = path
        self.competitor = competitor
        self.dimension = dimension
        self.urls = urls or []
        self.errors: list[dict[str, str]] = []

    def load_records(self) -> list[IntelligenceRecord]:
        if self.source_type == "csv":
            return load_csv(self.path)
        if self.source_type == "agri_daily":
            return fetch_agri_daily_reports(
                self.urls or ([self.url] if self.url else []),
                on_error=self.errors.append,
            )
        if self.source_type == "rss":
            return fetch_rss(self.url, competitor=self.competitor, dimension=self.dimension)
        if self.source_type == "search_page":
            return fetch_search_page(self.url, competitor=self.competitor, dimension=self.dimension)
        if self.source_type in {"webpage", "forum"}:
            record = fetch_webpage(self.url, competitor=self.competitor, dimension=self.dimension)
            record.source_type = self.source_type
            return [record]
        raise ValueError(f"Unsupported source_type: {self.source_type}")

    def load(self) -> list[Document]:
        documents = []
        for record in self.load_records():
            documents.append(
                Document(
                    page_content=record.content,
                    metadata={
                        "record_id": record.record_id,
                        "title": record.title,
                        "source_url": record.source_url,
                        "source_type": record.source_type,
                        "competitor": record.competitor,
                        "dimension": record.dimension,
                        "collected_at": record.collected_at,
                        "source_name": record.source_name,
                        "published_at": record.published_at,
                    },
                )
            )
        return documents
