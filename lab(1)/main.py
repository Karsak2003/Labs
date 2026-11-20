#!/usr/bin/env python3
"""
Практика 1: "Интеллектуальный анализ веб-данных" 
Консольное приложение для поиска по архиву Common Crawl.
Использует CDX-индекс для быстрого поиска и WARC-файлы
для точечной загрузки содержимого страниц.
"""

import argparse
import sys
from datetime import datetime

import cdx_toolkit
import httpx
from bs4 import BeautifulSoup
from tabulate import tabulate
from warcio.archiveiterator import ArchiveIterator


# ============================================================
# 1. Парсер аргументов CLI (argparse)
# ============================================================
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Поиск по архиву Common Crawl через CDX-индекс",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Примеры:\n"
            "  python cc_search.py Пермь ПНИПУ --domain pstu.ru --limit 5\n"
            "  python cc_search.py Python --limit 20 --show-text\n"
        ),
    )
    parser.add_argument(
        "keywords",
        nargs="+",
        help="Одно или несколько ключевых слов для поиска",
    )
    parser.add_argument(
        "--domain",
        default=None,
        help="Фильтр по домену (например, pstu.ru)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Ограничение числа результатов (по умолчанию 10)",
    )
    parser.add_argument(
        "--show-text",
        action="store_true",
        help="Загрузить и показать фрагмент текста страницы (через WARC)",
    )
    return parser


# ============================================================
# 2. Функция поиска по CDX-индексу
# ============================================================
def search_cdx(keywords: list[str], domain: str | None, limit: int) -> list[dict]:
    """
    Ищет по CDX-индексу Common Crawl.
    Возвращает список словарей с полями:
      url, timestamp, status, mime, offset, length, filename
    """
    cdx = cdx_toolkit.CDXFetcher()

    # Формируем запрос: если указан домен — ищем по нему,
    # иначе ищем по первому ключевому слову как по URL-шаблону
    url_pattern = f"*{domain}*" if domain else f"*{keywords[0]}*"

    results = []
    iterator = cdx.iter(
        url=url_pattern,
        limit=limit,
        # filter: все ключевые слова должны встречаться в URL
        filters=[f"urlkey:{kw.lower()}" for kw in keywords] if not domain else None,
    )

    for item in iterator:
        results.append({
            "url": item.get("url"),
            "timestamp": item.get("timestamp"),
            "status": item.get("status"),
            "mime": item.get("mime"),
            "offset": int(item.get("offset", 0)),
            "length": int(item.get("length", 0)),
            "filename": item.get("filename"),
        })
        if len(results) >= limit:
            break

    return results


# ============================================================
# 3. Загрузка и парсинг WARC через Range-запрос
# ============================================================
CC_BASE_URL = "https://data.commoncrawl.org/"


def fetch_warc_record(filename: str, offset: int, length: int) -> str | None:
    """
    Загружает конкретный WARC-запись через HTTP Range.
    Возвращает HTML-контент или None.
    """
    url = CC_BASE_URL + filename
    headers = {"Range": f"bytes={offset}-{offset + length - 1}"}

    try:
        with httpx.stream("GET", url, headers=headers, timeout=30.0) as resp:
            resp.raise_for_status()
            # warcio работает с потоком байт
            data = resp.read()

        # Ищем первый warcinfo или response-запись
        from io import BytesIO
        for record in ArchiveIterator(BytesIO(data)):
            if record.rec_type == "response":
                payload = record.content_stream().read()
                return payload.decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"[!] Ошибка загрузки WARC: {e}", file=sys.stderr)
    return None


def extract_text_and_title(html: str, max_chars: int = 200) -> tuple[str, str]:
    """
    Извлекает title и фрагмент текста из HTML.
    """
    soup = BeautifulSoup(html, "html.parser")

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    # Убираем скрипты и стили
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    text = soup.get_text(separator=" ", strip=True)
    # Схлопываем пробелы
    text = " ".join(text.split())
    snippet = text[:max_chars] + ("..." if len(text) > max_chars else "")
    return title, snippet


# ============================================================
# 4. Форматированный вывод через tabulate
# ============================================================
def format_timestamp(ts: str) -> str:
    """Преобразует '20240315123456' → '2024-03-15 12:34:56'."""
    if not ts or len(ts) < 14:
        return ts or "—"
    try:
        dt = datetime.strptime(ts[:14], "%Y%m%d%H%M%S")
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return ts


def print_results(results: list[dict], show_text: bool) -> None:
    if not results:
        print("Ничего не найдено.")
        return

    headers = ["#", "URL", "Дата архивации", "Заголовок"]
    if show_text:
        headers.append("Фрагмент текста")

    rows = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "—") or "—"
        row = [
            i,
            r["url"],
            format_timestamp(r["timestamp"]),
            title[:80] + ("..." if len(title) > 80 else ""),
        ]
        if show_text:
            row.append(r.get("snippet", ""))
        rows.append(row)

    print(tabulate(rows, headers=headers, tablefmt="grid", maxcolwidths=[None, 60, 20, 40]))


# ============================================================
# Основная логика
# ============================================================
def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    print(f"🔎 Поиск: {', '.join(args.keywords)}")
    if args.domain:
        print(f"🌐 Домен: {args.domain}")
    print(f"📊 Лимит: {args.limit}")
    print("─" * 60)

    # Шаг 1: поиск по CDX
    print("⏳ Поиск по CDX-индексу...")
    results = search_cdx(args.keywords, args.domain, args.limit)
    print(f"✅ Найдено записей: {len(results)}\n")

    if not results:
        return 0

    # Шаг 2: опциональная загрузка WARC
    if args.show_text:
        print("⏳ Загрузка содержимого страниц из WARC...")
        for i, r in enumerate(results, 1):
            print(f"  [{i}/{len(results)}] {r['url'][:60]}...")
            html = fetch_warc_record(r["filename"], r["offset"], r["length"])
            if html:
                title, snippet = extract_text_and_title(html)
                r["title"] = title
                r["snippet"] = snippet
            else:
                r["title"] = "— (не удалось загрузить)"
                r["snippet"] = ""
    else:
        # Без --show-text пытаемся хотя бы вытащить title из URL
        for r in results:
            r["title"] = ""

    # Шаг 3: вывод
    print()
    print_results(results, args.show_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())