BOT_NAME = "webscraper"
SPIDER_MODULES = ["webscraper.spiders"]
NEWSPIDER_MODULE = "webscraper.spiders"

# ── Этикет краулера ──
ROBOTSTXT_OBEY = True
CONCURRENT_REQUESTS = 4
CONCURRENT_REQUESTS_PER_DOMAIN = 2
DOWNLOAD_DELAY = 1.5
DOWNLOAD_DELAY_JITTER = 0.5      # вместо deprecated RANDOMIZE_DOWNLOAD_DELAY

# ── Retry ──
RETRY_ENABLED = True
RETRY_TIMES = 3
RETRY_HTTP_CODES = [429, 500, 502, 503, 504]
DOWNLOAD_TIMEOUT = 30

# ── Глубина: 0 = без лимита (DEPTH_LIMIT=10 обрезал пагинацию на page12) ──
DEPTH_LIMIT = 0

# ── Убираем предупреждение MemUsage на Windows ──
MEMUSAGE_ENABLED = False

DEFAULT_REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru,en;q=0.5",
}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

ITEM_PIPELINES = {
    "webscraper.pipelines.CleaningPipeline": 100,
    "webscraper.pipelines.DuplicationPipeline": 200,
    "webscraper.pipelines.ValidationPipeline": 300,
}

# ── Playwright ──
DOWNLOAD_HANDLERS = {
    "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
    "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
}
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
PLAYWRIGHT_BROWSER_TYPE = "chromium"
PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT = 45_000
PLAYWRIGHT_LAUNCH_OPTIONS = {"headless": True}

AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1.5
AUTOTHROTTLE_MAX_DELAY = 10

LOG_LEVEL = "INFO"
LOG_FILE_ENCODING = "utf-8"      # LOG_FILE задаётся из CLI