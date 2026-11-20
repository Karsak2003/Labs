#!/usr/bin/env python3
"""CLI search over the Common Crawl archive (CDX index + optional WARC text).

Pipeline (per course slides):
  1. argparse CLI contract
  2. CDX-only search via cdx-toolkit (no WARC at this stage)
  3. WARC Range-request loading, only with --show-text (warcio + bs4)
  4. Formatted table output (tabulate)

Resilience: disk cache of successful responses, circuit breaker,
wall-clock cap per query, polite pauses. Logs: English, ASCII, stderr.
"""

import argparse
import hashlib
import json
import logging
import pathlib
import re
import sys
import threading
import time
from datetime import datetime, timedelta
from io import BytesIO

import cdx_toolkit
import httpx
from bs4 import BeautifulSoup
from tabulate import tabulate
from warcio.archiveiterator import ArchiveIterator

LOG = logging.getLogger("cc_search")
CACHE_DIR = pathlib.Path("cdx_cache")
CC_DATA = "https://data.commoncrawl.org/"
CDX_FIELDS = ("url", "timestamp", "status", "mime", "offset", "length", "filename")


# ---------- logging ----------
def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stderr)],
    )
    # hide library retry/pagination spam (129-endpoint lists, 60s backoffs)
    logging.getLogger("cdx_toolkit").setLevel(logging.ERROR)
    logging.getLogger("urllib3").setLevel(logging.ERROR)


# ---------- stage 1: CLI ----------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Search Common Crawl archive via CDX index",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples (lab queries):\n"
            "  python cc_search.py Perm PNIPU --domain pstu.ru --limit 5\n"
            "  python cc_search.py ITAS --domain pstu.ru --limit 5 --show-text\n"
            "  python cc_search.py MSU --domain msu.ru --limit 10\n"
            "  python cc_search.py MIPT --domain mipt.ru --limit 10\n"
            "  python cc_search.py Pasternak Perm --domain permkrai.ru --limit 5 --show-text\n"
            "\nNote: CDX is a URL index, not full-text search. --domain defines\n"
            "the search area; keywords filter URLs (and page text with --show-text)."
        ),
    )
    p.add_argument("keywords", nargs="+", help="One or more keywords")
    p.add_argument("--domain", default=None, help="Domain filter, e.g. pstu.ru")
    p.add_argument("--limit", type=int, default=10, help="Max results (default: 10)")
    p.add_argument("--show-text", action="store_true", help="Load page text via WARC Range request")
    p.add_argument("--snapshot", default="CC-MAIN-2026-43", help="Crawl to query (default: CC-MAIN-2026-43)")
    p.add_argument("--from-ts", default=None, help="Override range start, YYYYMMDD[HHMMSS]")
    p.add_argument("--to-ts", default=None, help="Override range end, YYYYMMDD[HHMMSS]")
    p.add_argument("--max-retries", type=int, default=2, help="Attempts before circuit breaker (default: 2)")
    p.add_argument("--timeout", type=int, default=25, help="Wall-clock cap per CDX query, seconds (default: 25)")
    p.add_argument("--no-cache", action="store_true", help="Ignore fresh cache (still used as fallback on failure)")
    p.add_argument("--verbose", action="store_true", help="DEBUG logging")
    return p


# ---------- helpers ----------
def snapshot_range(snapshot: str) -> tuple[str, str]:
    """Map CC-MAIN-YYYY-WW to a capture date window (cdx-toolkit selects crawls by dates)."""
    m = re.fullmatch(r"CC-MAIN-(\d{4})(?:-(\d{1,2}))?", snapshot)
    if not m:
        raise ValueError(f"Bad snapshot name: {snapshot}")
    year, week = int(m.group(1)), m.group(2)
    if week:
        monday = datetime.strptime(f"{year}-W{int(week):02d}-1", "%G-W%V-%u")
        start, end = monday - timedelta(days=14), monday + timedelta(days=21)
    else:
        start, end = datetime(year, 1, 1), datetime(year, 12, 31)
    return start.strftime("%Y%m%d%H%M%S"), end.strftime("%Y%m%d%H%M%S")


def cache_path(kind: str, key: str) -> pathlib.Path:
    CACHE_DIR.mkdir(exist_ok=True)
    return CACHE_DIR / f"{kind}_{hashlib.sha1(key.encode()).hexdigest()[:16]}.json"


def load_cache(path: pathlib.Path):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def save_cache(path: pathlib.Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def with_timeout(fn, seconds: int):
    """Run fn in a daemon thread; abandon it if it exceeds the wall-clock cap."""
    box = {}

    def run():
        try:
            box["ok"] = fn()
        except Exception as e:  # noqa: BLE001
            box["err"] = e

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    if t.is_alive():
        raise TimeoutError(f"CDX query exceeded {seconds}s wall-clock cap")
    if "err" in box:
        raise box["err"]
    return box.get("ok", [])


# ---------- stage 2: CDX search ----------
def fetch_cdx_rows(pattern: str, from_ts: str, to_ts: str, fetch_limit: int) -> list[dict]:
    cdx = cdx_toolkit.CDXFetcher(source="cc")
    rows = []
    for obj in cdx.iter(pattern, limit=fetch_limit, from_ts=from_ts, to_ts=to_ts):
        data = obj if isinstance(obj, dict) else getattr(obj, "data", {})
        row = {k: data.get(k) for k in CDX_FIELDS}
        row["offset"] = int(row.get("offset") or 0)
        row["length"] = int(row.get("length") or 0)
        rows.append(row)
        if len(rows) >= fetch_limit:
            break
    return rows


def search_cdx(args, pattern: str) -> list[dict]:
    from_ts = args.from_ts or snapshot_range(args.snapshot)[0]
    to_ts = args.to_ts or snapshot_range(args.snapshot)[1]
    fetch_limit = min(args.limit * 5, 50)
    LOG.info("Query: url=%s range=%s..%s fetch_limit=%d", pattern, from_ts, to_ts, fetch_limit)

    cf = cache_path("cdx", f"{pattern}|{from_ts}|{to_ts}|{fetch_limit}")
    if not args.no_cache:
        cached = load_cache(cf)
        if cached is not None:
            LOG.info("Cache hit: %s (%d rows)", cf.name, len(cached))
            return cached

    for attempt in range(1, args.max_retries + 1):
        try:
            LOG.info("Attempt %d/%d: querying CDX index...", attempt, args.max_retries)
            rows = with_timeout(lambda: fetch_cdx_rows(pattern, from_ts, to_ts, fetch_limit), args.timeout)
            LOG.info("OK: received %d rows", len(rows))
            if rows:
                save_cache(cf, rows)
            return rows
        except Exception as e:  # noqa: BLE001
            LOG.error("Attempt %d failed: %s", attempt, e)
            if attempt < args.max_retries:
                pause = 3 * attempt
                LOG.info("Polite pause %ds before retry...", pause)
                time.sleep(pause)

    LOG.error("Circuit breaker: CDX service degraded. Falling back to cache if any.")
    return load_cache(cf) or []


# ---------- stage 3: WARC loading (--show-text only) ----------
def decode_payload(record) -> str:
    ctype = ""
    if record.http_headers:
        ctype = record.http_headers.get_header("Content-Type") or ""
    m = re.search(r"charset=([\w-]+)", ctype, re.I)
    payload = record.content_stream().read()
    for enc in ([m.group(1)] if m else []) + ["utf-8", "cp1251"]:
        try:
            return payload.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return payload.decode("utf-8", errors="replace")


def extract_text_and_title(html: str, max_chars: int = 200) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = " ".join(soup.get_text(separator=" ", strip=True).split())
    return title, text[:max_chars] + ("..." if len(text) > max_chars else "")


def fetch_warc_text(filename: str, offset: int, length: int) -> dict | None:
    cf = cache_path("warc", f"{filename}|{offset}|{length}")
    cached = load_cache(cf)
    if cached is not None:
        return cached
    if not filename or length <= 0:
        return None
    url = CC_DATA + filename
    headers = {"Range": f"bytes={offset}-{offset + length - 1}"}
    for attempt in range(1, 3):
        try:
            with httpx.stream("GET", url, headers=headers, timeout=30.0) as resp:
                resp.raise_for_status()
                data = resp.read()
            for record in ArchiveIterator(BytesIO(data)):
                if record.rec_type == "response":
                    title, snippet = extract_text_and_title(decode_payload(record))
                    rec = {"title": title, "snippet": snippet}
                    save_cache(cf, rec)
                    return rec
            LOG.warning("WARC record has no response: %s", filename)
            return None
        except Exception as e:  # noqa: BLE001
            LOG.error("WARC load error (attempt %d): %s", attempt, e)
            time.sleep(1)  # polite rate: <= 1 request/second
    return None


# ---------- stage 4: output ----------
def fmt_ts(ts) -> str:
    ts = str(ts or "")
    if len(ts) < 14:
        return ts or "-"
    try:
        return datetime.strptime(ts[:14], "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return ts


def keyword_filter(rows: list[dict], keywords: list[str], with_text: bool = False):
    kws = [k.lower() for k in keywords]
    hits = []
    for r in rows:
        hay = r.get("url", "").lower()
        if with_text:
            hay += " " + (r.get("title", "") + " " + r.get("snippet", "")).lower()
        if any(k in hay for k in kws):
            hits.append(r)
    return (hits, True) if hits else (rows, False)


def print_table(rows: list[dict], show_text: bool) -> None:
    headers = ["#", "URL", "Archive Date", "Title"]
    widths = [None, 60, 19, 40]
    if show_text:
        headers.append("Text Fragment")
        widths.append(60)
    table = []
    for i, r in enumerate(rows, 1):
        title = r.get("title") or "-"
        row = [i, r.get("url", "-"), fmt_ts(r.get("timestamp")), title[:80]]
        if show_text:
            row.append(r.get("snippet", ""))
        table.append(row)
    print(tabulate(table, headers=headers, tablefmt="grid", maxcolwidths=widths))


# ---------- main ----------
def main() -> int:
    args = build_parser().parse_args()
    setup_logging(args.verbose)

    domain = (args.domain or "").lower().removeprefix("www.")
    if domain:
        pattern = f"*.{domain}"
    elif "." in args.keywords[0]:
        pattern = f"*.{args.keywords[0].lower()}"
    else:
        LOG.error("CDX is a URL index, not full-text search. Specify --domain (e.g. --domain pstu.ru).")
        return 2

    LOG.info("Search: keywords=%s domain=%s limit=%d snapshot=%s show_text=%s",
             ",".join(args.keywords), domain or "-", args.limit, args.snapshot, args.show_text)

    rows = search_cdx(args, pattern)
    if not rows:
        LOG.error("No results. Service may be degraded: check https://status.commoncrawl.org/ and retry later.")
        return 1

    rows, matched = keyword_filter(rows, args.keywords)
    if not matched:
        LOG.warning("Keywords not found in URLs; showing domain candidates (use --show-text for text match).")
    rows = rows[: args.limit]

    if args.show_text:
        LOG.info("Loading page content from WARC (Range requests)...")
        for i, r in enumerate(rows, 1):
            LOG.info("[%d/%d] %s", i, len(rows), r.get("url", "-")[:70])
            rec = fetch_warc_text(r.get("filename"), r.get("offset", 0), r.get("length", 0))
            if rec:
                r.update(rec)
            else:
                r["title"], r["snippet"] = "- (load failed)", ""
            time.sleep(1)
        rows, matched = keyword_filter(rows, args.keywords, with_text=True)
        if not matched:
            LOG.warning("Keywords not found in page text; showing all loaded candidates.")
    else:
        for r in rows:
            r["title"], r["snippet"] = "-", ""

    print()
    print_table(rows, args.show_text)
    LOG.info("Done. %d rows shown.", len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())