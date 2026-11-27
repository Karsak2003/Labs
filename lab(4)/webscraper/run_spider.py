#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings


def build_parser():
    p = argparse.ArgumentParser(
        description="Scrapy: news (SSR) + ecommerce (Playwright)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Примеры:\n"
            '  python run_spider.py --spider news --domain habr.com '
            '--start-path "ru/articles/" --output news.json\n'
            '  python run_spider.py --spider ecommerce --domain webscraper.io '
            '--start-path "test-sites/e-commerce/allinone/computers/laptops" '
            '--output products.csv\n'
        ),
    )
    p.add_argument("--spider", required=True, choices=["news", "ecommerce"])
    p.add_argument("--domain", required=True)
    p.add_argument("--start-path", default="")
    p.add_argument("--output", required=True)
    p.add_argument("--limit", type=int, default=120,
                   help="остановиться после N собранных записей (минимум по заданию — 100)")
    p.add_argument("--max-pages", type=int, default=30)
    p.add_argument("--pages", type=int, default=1, help="страниц ?page=N для ecommerce")
    p.add_argument("--keywords")
    p.add_argument("--logfile", default="run.log")
    p.add_argument("--log-level", default="INFO")
    p.add_argument("--probe", action="store_true", help="сохранить HTML для отладки")
    p.add_argument("--no-playwright", action="store_true")
    return p


def main():
    args = build_parser().parse_args()
    out = Path(args.output)
    fmt = "json" if out.suffix.lower() == ".json" else "csv"

    s = get_project_settings()
    s.set("FEEDS", {str(out): {"format": fmt, "encoding": "utf-8", "mode": "overwrite"}})
    s.set("CLOSESPIDER_ITEMCOUNT", args.limit)
    s.set("LOG_FILE", args.logfile)          # ← Scrapy сам пишет UTF-8
    s.set("LOG_FILE_ENCODING", "utf-8")
    s.set("LOG_LEVEL", args.log_level)

    print(f"паук={args.spider} домен={args.domain} путь={args.start_path or '/'}")
    print(f"лимит={args.limit} лог={args.logfile} вывод={out}")

    process = CrawlerProcess(s)
    if args.spider == "news":
        process.crawl("news", domain=args.domain, start_path=args.start_path,
                      keywords=args.keywords, max_pages=args.max_pages, probe=args.probe)
    else:
        process.crawl("ecommerce", domain=args.domain, start_path=args.start_path,
                      pages=args.pages, use_playwright=not args.no_playwright,
                      probe=args.probe)
    process.start()

    # Итог
    n = 0
    if out.exists():
        if fmt == "json":
            n = len(json.loads(out.read_text(encoding="utf-8") or "[]"))
        else:
            n = max(0, len(out.read_text(encoding="utf-8").splitlines()) - 1)
    print(f"\nзаписей в файле: {n}")
    if n < 100:
        print("⚠ меньше 100 — увеличьте --max-pages / --pages или ослабьте --keywords")
    return 0 if n else 1


if __name__ == "__main__":
    sys.exit(main())