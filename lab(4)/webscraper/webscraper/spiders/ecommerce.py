import re

import scrapy
from scrapy_playwright.page import PageMethod


class EcommerceSpider(scrapy.Spider):
    name = "ecommerce"

    CARD_SELECTORS = [
        ".thumbnail", ".card", ".product-card", ".ProductCard",
        "[data-product]", ".goods-item", "article.product",
    ]
    TITLE_TEXT = ["a.title ::text", "h4 a ::text", "h3 a ::text", ".card-title a ::text", "h2 a ::text"]
    TITLE_ATTR = ["a.title::attr(title)", "a::attr(title)"]
    URL_SELECTORS = ["a.title::attr(href)", "h4 a::attr(href)", "h3 a::attr(href)", "a::attr(href)"]
    PRICE_SELECTORS = [".price ::text", "h4.price ::text", ".product-price ::text",
                       ".Price__currentPrice ::text", "[data-price]::attr(data-price)"]
    DESC_SELECTORS = [".description ::text", ".card-text ::text", "p ::text"]
    REVIEWS_SELECTORS = [".review-count ::text", ".reviews ::text"]
    RATING_ATTR = ["p[data-rating]::attr(data-rating)", "[data-rating]::attr(data-rating)"]
    IMG_SELECTORS = ["img::attr(src)", "img::attr(data-src)"]

    def __init__(self, domain=None, start_path="", pages=1, use_playwright=True,
                 probe=False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not domain:
            raise ValueError("нужен --domain")

        self.domain = domain
        self.allowed_domains = [domain]
        self.base_path = start_path.strip("/")
        self.pages = max(1, int(pages))
        self.use_playwright = str(use_playwright).lower() in ("1", "true", "yes")
        self.probe = str(probe).lower() in ("1", "true", "yes")
        self.count = 0

        self.logger.info(f"Домен: {domain} | путь: {self.base_path or '/'} | "
                         f"playwright={self.use_playwright}")

    # ---------- URL ----------
    def _urls(self):
        base = f"https://{self.domain}/{self.base_path}" if self.base_path \
            else f"https://{self.domain}/"
        if self.pages == 1:
            return [base]
        sep = "&" if "?" in base else "?"
        return [f"{base}{sep}page={n}" for n in range(1, self.pages + 1)]

    def _request(self, url):
        return scrapy.Request(
            url,
            callback=self.parse,
            errback=self.errback,
            dont_filter=True,
            meta={
                "playwright": True,
                "playwright_page_methods": [
                    PageMethod("wait_for_selector", ", ".join(self.CARD_SELECTORS),
                               timeout=30_000, state="attached"),
                    PageMethod("evaluate", "window.scrollTo(0, document.body.scrollHeight)"),
                    PageMethod("wait_for_timeout", 1500),
                ],
            },
        )

    # ---------- Scrapy 2.13+ ----------
    async def start(self):
        for url in self._urls():
            self.logger.info(f"запрос: {url}")
            yield self._request(url)

    # ---------- fallback для старых версий ----------
    def start_requests(self):
        for url in self._urls():
            self.logger.info(f"запрос: {url}")
            yield self._request(url)

    # ---------- хелперы ----------
    def _text(self, node, selectors):
        for sel in selectors:
            parts = node.css(sel).getall()
            t = " ".join(p.strip() for p in parts if p.strip())
            if t:
                return t
        return None

    def _attr(self, node, selectors):
        for sel in selectors:
            v = node.css(sel).get()
            if v:
                return v.strip()
        return None

    @staticmethod
    def _price(text):
        """'1 234,56 ₽' → 1234.56 ; '$1,139.54' → 1139.54"""
        if not text:
            return None
        t = text.replace("\xa0", "").replace(" ", "").replace("\u2009", "")
        if "," in t and "." in t:
            t = t.replace(",", "")
        elif "," in t:
            t = t.replace(",", ".")
        m = re.search(r"\d+(?:\.\d+)?", t)
        return float(m.group()) if m else None

    @staticmethod
    def _int(text):
        if not text:
            return None
        m = re.search(r"\d+", text.replace(" ", ""))
        return int(m.group()) if m else None

    # ---------- парсинг ----------
    def parse(self, response):          # обычный sync — page больше нет
        cards = []
        for sel in self.CARD_SELECTORS:
            cards = response.css(sel)
            if cards:
                break
        for c in cards:
            yield {...}

    def errback(self, failure):         # синхронный, к page не обращаемся
        self.logger.error(f"ошибка {failure.request.url}: {failure.value}")