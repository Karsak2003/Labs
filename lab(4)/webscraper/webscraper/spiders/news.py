import scrapy


class NewsSpider(scrapy.Spider):
    name = "news"

    # ВАЖНО: пробел перед ::text = текст всех потомков (//text())
    ARTICLE_SELECTORS = [
        "article.tm-articles-list__item",
        "article",
        "div.article",
        "div.post",
        "[itemtype*='NewsArticle']",
    ]
    TITLE_SELECTORS = [
        "h2 a ::text",
        "a.tm-title__link ::text",
        "h2 ::text",
        "h1 ::text",
        "h3 a ::text",
        ".title ::text",
    ]
    URL_SELECTORS = [
        "h2 a::attr(href)",
        "a.tm-title__link::attr(href)",
        "h3 a::attr(href)",
        "a::attr(href)",
    ]
    DATE_SELECTORS = ["time::attr(datetime)", "time ::text", ".date ::text"]
    AUTHOR_SELECTORS = ["a[href*='/users/'] ::text", ".author ::text", "[rel='author'] ::text"]
    SUMMARY_SELECTORS = [
        ".tm-article-body ::text",
        ".tm-article-presenter__snippet ::text",
        "p ::text",
        ".description ::text",
        ".summary ::text",
    ]
    TAGS_SELECTORS = ["a[href*='/hubs/'] ::text", "a.tm-tags__item-link ::text", ".tags a ::text"]

    def __init__(self, domain=None, start_path="", keywords=None,
                 max_pages=30, probe=False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not domain:
            raise ValueError("нужен --domain")

        self.domain = domain
        self.allowed_domains = [domain]
        self.start_urls = [f"https://{domain}/{start_path.lstrip('/')}"]
        self.keywords = [k.strip().lower() for k in keywords.split(",")] if keywords else []
        self.max_pages = int(max_pages)
        self.probe = str(probe).lower() in ("1", "true", "yes")
        self.count = 0
        self.pages_done = 0

        self.logger.info(f"Домен: {domain} | start: {self.start_urls[0]}")

    # ---------- хелперы ----------
    def _text(self, node, selectors):
        """Первый непустой текст (склейка всех потомков)."""
        for sel in selectors:
            parts = node.css(sel).getall()
            text = " ".join(p.strip() for p in parts if p.strip())
            if text:
                return text
        return None

    def _attr(self, node, selectors):
        for sel in selectors:
            v = node.css(sel).get()
            if v:
                return v.strip()
        return None

    def _all_text(self, node, selectors):
        for sel in selectors:
            parts = [p.strip() for p in node.css(sel).getall() if p.strip()]
            if parts:
                return list(dict.fromkeys(parts))
        return []

    # ---------- парсинг ----------
    def parse(self, response):
        self.pages_done += 1
        self.logger.info(f"[стр. {self.pages_done}] {response.url} — {response.status}")

        if self.probe:
            with open("debug_news.html", "w", encoding="utf-8") as f:
                f.write(response.text)
            self.logger.info("HTML сохранён в debug_news.html")

        articles = []
        for sel in self.ARTICLE_SELECTORS:
            articles = response.css(sel)
            if articles:
                self.logger.info(f"селектор '{sel}' → {len(articles)} блоков")
                break

        if not articles:
            self.logger.error("блоки статей не найдены — смотрите debug_news.html")
            return

        empty_titles = 0
        for art in articles:
            title = self._text(art, self.TITLE_SELECTORS)
            href = self._attr(art, self.URL_SELECTORS)

            if not title or not href:
                empty_titles += 1
                continue

            summary = (self._text(art, self.SUMMARY_SELECTORS) or "")[:500]

            if self.keywords:
                hay = f"{title} {summary}".lower()
                if not any(k in hay for k in self.keywords):
                    continue

            self.count += 1
            yield {
                "title": title,
                "url": response.urljoin(href),
                "date": self._text(art, self.DATE_SELECTORS),
                "author": self._text(art, self.AUTHOR_SELECTORS),
                "summary": summary,
                "tags": self._all_text(art, self.TAGS_SELECTORS),
                "source": self.domain,
            }

        if empty_titles:
            self.logger.warning(f"без title/url пропущено блоков: {empty_titles}")
        self.logger.info(f"отдано записей всего: {self.count}")

        # ---------- пагинация ----------
        if self.pages_done >= self.max_pages:
            self.logger.info("достигнут --max-pages")
            return

        next_href = (
            response.css("a[rel='next']::attr(href)").get()
            or response.xpath(
                "//a[contains(., 'Туда') or contains(., 'Следующая') "
                "or contains(., 'Next') or contains(., '→')]/@href"
            ).get()
            or response.css("a.next::attr(href)").get()
            or response.css("a.tm-pagination__item_link[aria-label='Следующая']::attr(href)").get()
        )
        if next_href:
            yield scrapy.Request(
                response.urljoin(next_href),
                callback=self.parse,
                errback=self.errback,      # ← аргумент, а не meta!
            )
        else:
            self.logger.info("пагинация закончилась")

    def errback(self, failure):
        self.logger.error(f"ошибка запроса {failure.request.url}: {failure.value}")