# WebScraper — система сбора веб-данных на Scrapy + Playwright

Лабораторная работа №4 по курсу «Интеллектуальный анализ веб-данных».
Production-ready система сбора с двух типов сайтов: статических новостных (SSR)
и динамических магазинов (SPA) с полной цепочкой предобработки данных.

---

## Содержание

- [Назначение](#назначение)
- [Соответствие требованиям ЛР №4](#соответствие-требованиям-лр-4)
- [Стек](#стек)
- [Структура проекта](#структура-проекта)
- [Установка](#установка)
- [Быстрый старт](#быстрый-старт)
- [Справочник CLI](#справочник-cli)
- [Пауки](#пауки)
- [Pipelines](#pipelines)
- [Схема данных](#схема-данных)
- [Настройки и обработка ошибок](#настройки-и-обработка-ошибок)
- [Экспорт данных](#экспорт-данных)
- [Диагностика](#диагностика)
- [Проверка качества данных](#проверка-качества-данных)
- [Возможные ошибки](#Возможные-ошибки)
- [Этические и правовые ограничения](#этические-и-правовые-ограничения)

---

## Назначение

Проект решает задачу сбора и **предварительной обработки** веб-данных:

1. Обход страниц сайта с пагинацией (Scrapy, асинхронно).
2. Рендеринг JavaScript для SPA (Playwright через `scrapy-playwright`).
3. Извлечение структурированных полей (CSS-селекторы с fallback).
4. Очистка: исправление кодировок (`ftfy`), нормализация пробелов.
5. Дедупликация по URL.
6. Валидация обязательных полей.
7. Экспорт в JSON / CSV.

Ключевая особенность: **домен и путь сайта передаются через CLI**, а не
зашиты в код. Пауки универсальны и переиспользуемы.

---

## Соответствие требованиям ЛР №4

| № | Требование презентации | Реализация | Файл |
|---|------------------------|-----------|------|
| 1 | Scrapy-проект с двумя пауками | `NewsSpider` + `EcommerceSpider` | `spiders/news.py`, `spiders/ecommerce.py` |
| 1a | NewsSpider для SSR | обычный `scrapy.Request`, CSS-селекторы | `spiders/news.py` |
| 1b | EcommerceSpider для SPA | `meta={"playwright": True}` + `PageMethod` | `spiders/ecommerce.py` |
| 2 | ≥ 100 записей на паука | `CLOSESPIDER_ITEMCOUNT` (по умолч. 120) | `run_spider.py` |
| 3a | `CleaningPipeline` (ftfy, strip) | `ftfy.fix_text` + `re.sub(r"\s+", " ")` | `pipelines.py` |
| 3b | `DuplicationPipeline` | MD5-хэш URL в `set`, `DropItem` | `pipelines.py` |
| 3c | `ValidationPipeline` | проверка обязательных полей | `pipelines.py` |
| 4 | Retry для HTTP 429/503 + логирование | `RETRY_HTTP_CODES`, `self.logger` | `settings.py`, пауки |
| 5 | CLI `--spider --keywords --output` | `argparse` + `CrawlerProcess` | `run_spider.py` |
| 6 | Экспорт в JSON и CSV | `FEEDS` по расширению файла | `run_spider.py` |
| 7 | Опционально: Docker / Anti-Captcha / Redis | **не реализовано** (см. ниже) | — |

---

## Стек

| Компонент | Версия (проверено) | Назначение |
|-----------|--------------------|-----------|
| Python | 3.14.3 | язык |
| Scrapy | 2.20.0 | фреймворк краулинга |
| scrapy-playwright | 0.0.48 | интеграция браузера |
| Playwright | 1.65.2 | JS-рендеринг (Chromium) |
| parsel | 1.12.1 | CSS/XPath-селекторы |
| lxml | 6.1.3 | быстрый HTML-парсер |
| ftfy | ≥ 6.1 | исправление битых кодировок |
| itemadapter | ≥ 0.8 | единый доступ к полям item |

---

## Структура проекта

```
webscraper/
├── scrapy.cfg                  # точка входа Scrapy
├── run_spider.py               # CLI-обёртка (argparse + CrawlerProcess)
├── requirements.txt
├── README.md
├── REPORT.md                   # отчёт по лабораторной
├── check_data.py               # утилита проверки качества данных
└── webscraper/
    ├── __init__.py
    ├── items.py                # NewsItem, ProductItem
    ├── pipelines.py            # Cleaning → Duplication → Validation
    ├── settings.py             # retry, throttling, Playwright, логи
    ├── middlewares.py
    └── spiders/
        ├── __init__.py
        ├── news.py             # NewsSpider (SSR)
        └── ecommerce.py        # EcommerceSpider (SPA)
```

Артефакты, создаваемые при работе:

```
news.json / products.csv        # результат экспорта
run.log                         # лог (UTF-8)
debug_news.html                 # HTML при --probe (news)
debug_ecom.html                 # HTML при --probe (ecommerce)
```

---

## Установка

### 1. Виртуальное окружение

```bash
python -m venv .venv

# Windows (PowerShell)
.venv\Scripts\Activate.ps1

# Linux / macOS
source .venv/bin/activate
```

> Если PowerShell блокирует активацию:
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`

### 2. Зависимости Python

```bash
pip install -r requirements.txt
```

`requirements.txt`:

```
scrapy>=2.13
scrapy-playwright>=0.0.40
playwright>=1.40
ftfy>=6.1
itemadapter>=0.8
lxml>=5.0
pandas>=2.0        # для check_data.py
```

### 3. Браузер для Playwright

```bash
playwright install chromium

# Linux — дополнительно системные библиотеки
playwright install-deps chromium
```

### 4. Проверка

```bash
scrapy version -v
python run_spider.py --help
```

---

## Быстрый старт

```bash
# Новости (SSR), сбор 120 записей в JSON
python run_spider.py --spider news \
  --domain habr.com --start-path "ru/articles/" \
  --limit 120 --output news.json

# Товары (SPA + Playwright), сбор в CSV
python run_spider.py --spider ecommerce \
  --domain webscraper.io \
  --start-path "test-sites/e-commerce/allinone/computers/laptops" \
  --limit 120 --output products.csv
```

После запуска скрипт печатает фактическое число записей в файле и
предупреждает, если их меньше 100.

---

## Справочник CLI

```
python run_spider.py --spider {news|ecommerce} --domain DOMAIN
                     [--start-path PATH] --output FILE
                     [--limit N] [--max-pages N] [--pages N]
                     [--keywords LIST] [--logfile FILE]
                     [--log-level LEVEL] [--probe] [--no-playwright]
```

| Аргумент | Тип | По умолчанию | Описание |
|----------|-----|--------------|----------|
| `--spider` | выбор | **обязателен** | `news` или `ecommerce` |
| `--domain` | str | **обязателен** | домен сайта, напр. `habr.com` |
| `--start-path` | str | `""` | путь внутри сайта, напр. `ru/articles/` |
| `--output` | str | **обязателен** | файл результата; `.json` → JSON, иначе CSV |
| `--limit` | int | `120` | остановка после N **сохранённых** записей (`CLOSESPIDER_ITEMCOUNT`) |
| `--max-pages` | int | `30` | максимум страниц пагинации (news) |
| `--pages` | int | `1` | число URL `?page=N` (ecommerce) |
| `--keywords` | str | `None` | фильтр новостей, через запятую: `"ИИ,Python"` |
| `--logfile` | str | `run.log` | файл лога; Scrapy пишет UTF-8 сам |
| `--log-level` | str | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `--probe` | флаг | выкл. | сохранить HTML страницы для отладки селекторов |
| `--no-playwright` | флаг | выкл. | отключить браузер (быстрая проверка конвейера) |

### Примеры

```bash
# Фильтрация новостей по ключевым словам
python run_spider.py --spider news --domain habr.com \
  --start-path "ru/articles/" --keywords "ИИ,машинное обучение" \
  --output news_ai.json

# Отладка: сохранить HTML + подробный лог
python run_spider.py --spider news --domain habr.com \
  --start-path "ru/articles/" --probe --log-level DEBUG \
  --output news.json

# Обход 6 страниц каталога без браузера
python run_spider.py --spider ecommerce --domain books.toscrape.com \
  --start-path "catalogue/page-1.html" --pages 6 --no-playwright \
  --output books.json
```

> **PowerShell:** перенос строки — обратная кавычка `` ` ``, а не `\`.
> Либо пишите команду в одну строку.

---

## Пауки

### NewsSpider (`name = "news"`)

**Назначение:** статические новостные сайты с server-side rendering.

Алгоритм:

1. Формирует `start_urls = [f"https://{domain}/{start_path}"]`.
2. Ищет блоки статей, перебирая `ARTICLE_SELECTORS` до первого совпадения.
3. Из каждого блока извлекает `title`, `url`, `date`, `author`, `summary`, `tags`.
4. Фильтрует по `--keywords` (по подстроке в `title + summary`, без учёта регистра).
5. Ищет ссылку «следующая страница» (`a[rel=next]`, текст «Туда»/«Следующая»/«Next»).
6. Повторяет до `--limit` или `--max-pages`.

**Критично: пробел перед `::text`.**
В parsel `::text` берёт только прямые текстовые узлы:

| Селектор | XPath | Результат на `<h2><a><span>Заголовок</span></a></h2>` |
|----------|-------|------------------------------------------------------|
| `h2 a::text` | `h2/a/text()` | `None` ❌ |
| `h2 a ::text` | `h2/a//text()` | `"Заголовок"` ✅ |

Поэтому все текстовые селекторы используют ` ::text` + `.getall()` + склейку.

### EcommerceSpider (`name = "ecommerce"`)

**Назначение:** динамические магазины (React/Vue), контент появляется после JS.

Алгоритм:

1. Генерирует URL `?page=1..N`.
2. Каждый запрос идёт через Playwright:
   ```python
   meta = {
       "playwright": True,
       "playwright_include_page": True,
       "playwright_page_methods": [
           PageMethod("wait_for_selector", CARD_SELECTORS, timeout=30_000),
           PageMethod("evaluate", "window.scrollTo(0, document.body.scrollHeight)"),
           PageMethod("wait_for_timeout", 1500),
       ],
   }
   ```
3. Извлекает `title`, `url`, `price`, `rating`, `reviews_count`, `image_url`, `description`.
4. В `finally` закрывает страницу браузера (иначе утечка процессов).

**Совместимость версий Scrapy.** Определены оба метода:

```python
async def start(self):        # Scrapy 2.13+
    ...
def start_requests(self):     # fallback для старых версий
    ...
```

Причина: в Scrapy 2.13 `start_requests()` объявлен устаревшим; на 2.20 в наших
прогонах он не вызывался вовсе (0 запросов). Новый Scrapy берёт `start()`,
старый — `start_requests()`.

### Как добавить новый сайт

1. Запустите с `--probe --log-level DEBUG`.
2. Откройте `debug_news.html` / `debug_ecom.html` в браузере, нажмите F12.
3. Найдите реальные классы карточек/статей.
4. Добавьте селекторы **в начало** соответствующего списка в пауке:
   ```python
   ARTICLE_SELECTORS = ["div.my-site-article", ...]  # свой — первым
   TITLE_SELECTORS   = ["h3 a ::text", ...]          # не забыть пробел
   ```
5. Перезапустите.

---

## Pipelines

Порядок задаётся приоритетом в `settings.py` (меньше = раньше):

```python
ITEM_PIPELINES = {
    "webscraper.pipelines.CleaningPipeline":    100,
    "webscraper.pipelines.DuplicationPipeline": 200,
    "webscraper.pipelines.ValidationPipeline":  300,
}
```

### 1. CleaningPipeline (100)

- `ftfy.fix_text()` — исправляет мохибейк (`РїСЂРёРІРµС‚` → `привет`).
- `re.sub(r"\s+", " ", value).strip()` — схлопывает пробелы, табы, переносы.
- Обрабатывает и строки, и списки строк (`tags`).
- `lower()` **не применяется** сознательно: сохраняет имена собственные
  (важно для NER и читаемости отчёта).

### 2. DuplicationPipeline (200)

- Ключ — `md5(url)`, хранится в `set` в памяти.
- Повтор → `DropItem("дубликат: …")`.
- Ограничение: состояние живёт только в рамках одного запуска.
  Для распределённого сбора нужен Redis (опциональное требование, не реализовано).

### 3. ValidationPipeline (300)

| Тип item | Обязательные поля |
|----------|-------------------|
| `NewsItem` | `title`, `url` |
| `ProductItem` | `title`, `url`, `price` |
| прочее (dict) | `title`, `url` |

Пустое/отсутствующее поле → `DropItem`. Счётчик отброшенных виден в статистике
Scrapy как `item_dropped_count`.

### Сигнатура `process_item`

```python
def process_item(self, item, *args, **kwargs):
```

В Scrapy 2.20 аргумент `spider` объявлен устаревшим. `*args` совместим и со
старыми версиями (передают 2 аргумента), и с новыми (передают 1), и не вызывает
`ScrapyDeprecationWarning`.

---

## Схема данных

### NewsItem

| Поле | Тип | Обяз. | Пример |
|------|-----|:-----:|--------|
| `title` | str | ✅ | `"Разработка в эпоху ИИ: часть 1"` |
| `url` | str | ✅ | `"https://habr.com/ru/articles/1112318/"` |
| `date` | str | — | `"2026-11-26T15:18:04.000Z"` |
| `author` | str | — | `"blognaumen"` |
| `summary` | str | — | первые 500 символов текста |
| `tags` | list[str] | — | `["Программирование", "Искусственный интеллект"]` |
| `source` | str | — | `"habr.com"` |

### ProductItem

| Поле | Тип | Обяз. | Пример |
|------|-----|:-----:|--------|
| `title` | str | ✅ | `"Asus VivoBook 15"` |
| `url` | str | ✅ | абсолютный URL товара |
| `price` | float | ✅ | `54990.0` |
| `old_price` | float | — | `64990.0` |
| `rating` | str | — | `"4"` (из `data-rating`) |
| `reviews_count` | int | — | `12` |
| `category` | str | — | путь каталога |
| `image_url` | str | — | абсолютный URL картинки |
| `description` | str | — | первые 400 символов |
| `source` | str | — | домен |

### Парсинг цены

Наивный `"".join(c for c in s if c.isdigit())` даёт ошибку на `$1,139.54`
(→ `113954`). Реализовано корректно:

```python
t = text.replace("\xa0", "").replace(" ", "")
if "," in t and "." in t:
    t = t.replace(",", "")     # 1,139.54 → 1139.54
elif "," in t:
    t = t.replace(",", ".")    # 1234,56  → 1234.56
m = re.search(r"\d+(?:\.\d+)?", t)
return float(m.group()) if m else None
```

---

## Настройки и обработка ошибок

Ключевые параметры `settings.py`:

```python
# Этикет краулера
ROBOTSTXT_OBEY = True
CONCURRENT_REQUESTS = 4
CONCURRENT_REQUESTS_PER_DOMAIN = 2
DOWNLOAD_DELAY = 1.5
DOWNLOAD_DELAY_JITTER = 0.5      # замена deprecated RANDOMIZE_DOWNLOAD_DELAY

# Retry
RETRY_ENABLED = True
RETRY_TIMES = 3
RETRY_HTTP_CODES = [429, 500, 502, 503, 504]
DOWNLOAD_TIMEOUT = 30

# Адаптивная задержка
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1.5
AUTOTHROTTLE_MAX_DELAY = 10

DEPTH_LIMIT = 0                  # 0 = без ограничения (иначе пагинация рвётся)
MEMUSAGE_ENABLED = False         # нет модуля resource на Windows

# Playwright
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
PLAYWRIGHT_BROWSER_TYPE = "chromium"
PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT = 45_000

LOG_FILE_ENCODING = "utf-8"
```

Уровни обработки ошибок:

| Уровень | Механизм | Где |
|---------|----------|-----|
| Сеть / HTTP 5xx / 429 | автоповтор до 3 раз | `RETRY_*` |
| Таймаут | 30 с загрузка, 45 с навигация | `DOWNLOAD_TIMEOUT`, Playwright |
| Ошибка запроса | `errback=self.errback` + лог | пауки |
| Пустой селектор | `if not title: continue` + warning | пауки |
| Битая запись | `DropItem` | `ValidationPipeline` |
| Дубликат | `DropItem` | `DuplicationPipeline` |

> `errback` передаётся **аргументом** `scrapy.Request(..., errback=...)`,
> а не через `meta={"errback": ...}` — во втором случае он молча игнорируется.

---

## Экспорт данных

Формат определяется расширением `--output`:

```python
fmt = "json" if out.suffix.lower() == ".json" else "csv"
settings.set("FEEDS", {
    str(out): {"format": fmt, "encoding": "utf-8", "mode": "overwrite"}
})
```

- `mode="overwrite"` — актуальный синтаксис (вместо устаревшего `overwrite=True`).
- Кодировка UTF-8. Для открытия CSV в Excel может потребоваться UTF-8 BOM
  (`"encoding": "utf-8-sig"`).
- Остановка по `CLOSESPIDER_ITEMCOUNT` считает записи, **прошедшие pipelines**,
  а не отданные пауком — поэтому `--limit 120` даёт запас над минимумом в 100.

---

## Диагностика

### Режим `--probe`

Сохраняет HTML обрабатываемой страницы:

- news → `debug_news.html`
- ecommerce → `debug_ecom.html`

Открывайте в браузере → F12 → сверяйте селекторы.

### Чтение лога

Лог пишется через настройку `LOG_FILE`, поэтому он в UTF-8:


> **Не используйте `2> run.log` в PowerShell** — он пишет UTF-16LE и
> превращает лог в нечитаемые символы, плюс помечает stderr как
> `NativeCommandError`.

### Что искать в статистике Scrapy

| Ключ статистики | О чём говорит |
|-----------------|---------------|
| `item_scraped_count` | сколько записей прошло pipelines |
| `item_dropped_count` | сколько отброшено (ищите причину в WARNING) |
| `downloader/request_count` отсутствует | паук не создал ни одного запроса |
| `downloader/response_status_count/404` | неверный `--start-path` |
| `downloader/response_status_count/429` | rate limit — увеличьте `DOWNLOAD_DELAY` |
| `depth/request_ignored_count` | упёрлись в `DEPTH_LIMIT` |
| `robotstxt/request_count` | проверка robots.txt выполнена |
| `finish_reason = closespider_itemcount` | достигнут `--limit` (норма) |

---

## Проверка качества данных

Утилита `check_data.py` реализует теоретическую часть лекции 4
(дубликаты, пропуски, выбросы):


Запуск:

```bash
python check_data.py news.json
python check_data.py products.csv
```

---

## Возможные ошибки

| Симптом | Причина | Решение |
|---------|---------|---------|
| `item_dropped_count: 20`, `title: None` | `::text` не достаёт текст из вложенного `<span>` | использовать ` ::text` (с пробелом) + `.getall()` |
| Нет ни одного `downloader/request_count` | `start_requests()` не вызывается в Scrapy 2.13+ | определить `async def start()` |
| `404` на первом запросе | неверный `--start-path` | сверить путь в браузере |
| Пагинация обрывается на 11–12 странице | `DEPTH_LIMIT = 10` | `DEPTH_LIMIT = 0` |
| Цена `113954` вместо `1139.54` | удалены все нецифровые символы | корректный парсер с учётом `,`/`.` |
| Лог — кракозябры | PowerShell `2>` пишет UTF-16LE | настройка `LOG_FILE` + `LOG_FILE_ENCODING` |
| `ScrapyDeprecationWarning: process_item() requires spider` | устаревшая сигнатура | `def process_item(self, item, *args, **kwargs)` |
| `RANDOMIZE_DOWNLOAD_DELAY is deprecated` | переименована настройка | `DOWNLOAD_DELAY_JITTER = 0.5` |
| `overwrite feed option is deprecated` | переименована опция | `mode="overwrite"` |
| `MemUsage extension requires resource` | нет модуля на Windows | `MEMUSAGE_ENABLED = False` |
| HTTP 403 / капча | антибот-защита | увеличить `DOWNLOAD_DELAY`, снизить `CONCURRENT_REQUESTS`, выбрать другой сайт |
| `Executable doesn't exist … chromium` | браузер не установлен | `playwright install chromium` |
| Ошибок нет, но записей 0 | селекторы не совпали | `--probe` → сверить классы в HTML |
| Записей < 100 | мало страниц / узкий фильтр | увеличить `--max-pages` / `--pages`, убрать `--keywords` |

---

## Этические и правовые ограничения

- `ROBOTSTXT_OBEY = True` по умолчанию — уважаем `robots.txt`.
- Задержка `DOWNLOAD_DELAY = 1.5` c джиттером + AutoThrottle — минимизация нагрузки.
- Не более 2 одновременных запросов на домен.
- Собираются только публичные данные, без авторизации и обхода капчи.
- Персональные данные не собираются (152-ФЗ / GDPR).
- Для учебных целей предпочтительны стенды: `webscraper.io`,
  `books.toscrape.com`, `quotes.toscrape.com` — они специально предназначены
  для тренировки скрапинга.
- Обход антибот-защиты может нарушать ToS сайта и законодательство
  (ст. 272 УК РФ, CFAA). В проекте не используется.

---