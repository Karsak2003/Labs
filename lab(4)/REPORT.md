# Отчёт по лабораторной работе №4

## Предварительная обработка и первичный анализ веб-данных
### Production-ready система сбора на Scrapy + Playwright

| | |
|---|---|
| **Дисциплина** | Интеллектуальный анализ веб-данных (Web Data Mining) |
| **Работа** | Лабораторная работа №4 |
| **Студент** | ⟨ФИО⟩ |
| **Группа** | ⟨номер группы⟩ |
| **Преподаватель** | ⟨ФИО преподавателя⟩ |
| **Дата выполнения** | ⟨дд.мм.гггг⟩ |
| **Репозиторий / папка** | ⟨путь или ссылка⟩ |

---

## 1. Цель и задачи

**Цель:** создать систему сбора данных с современных веб-сайтов,
реализовав полный цикл: сбор → предобработка → структурированный экспорт.

**Задачи (по постановке из презентации):**

1. Создать Scrapy-проект с двумя пауками:
   - `NewsSpider` — статические новостные сайты (SSR);
   - `EcommerceSpider` — динамические магазины (SPA, Playwright).
2. Каждый паук собирает **минимум 100 записей**.
3. Реализовать три pipeline: `CleaningPipeline`, `DuplicationPipeline`,
   `ValidationPipeline`.
4. Обработка ошибок: retry для HTTP 429/503, логирование.
5. CLI `run_spider.py` с аргументами `--spider`, `--keywords`, `--output`.
6. Экспорт в JSON и CSV.
7. *Опционально:* Docker, Anti-Captcha, Redis — **исключено из работы**
   по согласованию.

---

## 2. Теоретическое обоснование

Согласно лекции 4, классический пайплайн аналитики данных делится на три этапа:

| Этап | Доля времени | Инструменты |
|------|:------------:|-------------|
| Сбор | 10–15 % | requests, Scrapy, Playwright |
| **Обработка** | **70–80 %** | pandas, re, lxml, ftfy |
| Анализ | 10–15 % | sklearn, TensorFlow, PyTorch |

Основные проблемы веб-данных и способы их решения в проекте:

| Проблема | Последствие | Решение в проекте |
|----------|-------------|-------------------|
| Остатки HTML-разметки | нечитаемый текст | извлечение через CSS `::text`, без regex по HTML |
| Битые кодировки (мохибейк) | `РїСЂРёРІРµС‚` вместо `привет` | `ftfy.fix_text()` |
| Лишние пробелы, табы, переносы | ломает токенизацию и CSV | `re.sub(r"\s+", " ", …).strip()` |
| Точные дубликаты | искажение статистики | MD5-хэш URL + `DropItem` |
| Пропущенные значения | ломают агрегации | `ValidationPipeline`, отчёт `isna()` |
| Выбросы | искажают средние |检测 через IQR в `check_data.py` |
| Изменение вёрстки | парсер возвращает `None` | fallback-списки селекторов + логирование |
| JS-рендеринг | пустой `<div id="root">` | Playwright + `wait_for_selector` |

**Принципиальный выбор инструментов** (лекции 2–3):
статика → Scrapy CSS-селекторы; SPA → Playwright; массовый обход → Scrapy.
`lower()` в очистке не применяется сознательно — сохраняется регистр имён
собственных, что важно для последующего NER-анализа.

---

## 3. Архитектура решения

```
                    ┌──────────────────────┐
   CLI (argparse)   │    run_spider.py     │
                    └──────────┬───────────┘
                               │ CrawlerProcess + FEEDS
                    ┌──────────▼───────────┐
                    │   Scrapy Engine      │
                    │  retry · throttle    │
                    └────┬────────────┬────┘
             SSR         │            │        SPA
              ┌──────────▼──┐      ┌──▼──────────────┐
              │ NewsSpider  │      │ EcommerceSpider │
              │ CSS-селект. │      │ + Playwright    │
              └──────────┬──┘      └──┬──────────────┘
                         └──────┬─────┘
                          item  ▼
        ┌───────────────────────────────────────────┐
        │ 100 CleaningPipeline    (ftfy, strip)     │
        │ 200 DuplicationPipeline (md5 url, Drop)   │
        │ 300 ValidationPipeline  (required, Drop)  │
        └──────────────────┬────────────────────────┘
                           ▼
                  ┌──────────────────┐
                  │  FEEDS exporter  │
                  │  JSON  /  CSV    │
                  └──────────────────┘
```

Состав файлов:

| Файл | Роль |
|------|------|
| `run_spider.py` | CLI, конфигурация экспорта и лимита, итоговый подсчёт |
| `webscraper/settings.py` | retry, throttling, Playwright, pipelines, логи |
| `webscraper/items.py` | схемы `NewsItem`, `ProductItem` |
| `webscraper/pipelines.py` | три обязательных конвейера |
| `webscraper/spiders/news.py` | паук SSR |
| `webscraper/spiders/ecommerce.py` | паук SPA |
| `check_data.py` | контроль качества датасета |

---

## 4. Реализация

### 4.1. CLI

Реализован на `argparse`, запуск через `CrawlerProcess`. Обязательные по
постановке аргументы `--spider`, `--keywords`, `--output` присутствуют;
дополнительно введены `--domain` и `--start-path`, чтобы **не зашивать сайты
в код** и сделать пауки универсальными.

| Аргумент | По умолчанию | Назначение |
|----------|--------------|-----------|
| `--spider` | обязателен | `news` / `ecommerce` |
| `--domain` | обязателен | домен сайта |
| `--start-path` | `""` | путь внутри сайта |
| `--output` | обязателен | `.json` → JSON, иначе CSV |
| `--keywords` | — | фильтр новостей через запятую |
| `--limit` | `120` | `CLOSESPIDER_ITEMCOUNT`, запас над минимумом 100 |
| `--max-pages` | `30` | предел пагинации (news) |
| `--pages` | `1` | число URL `?page=N` (ecommerce) |
| `--logfile` | `run.log` | лог в UTF-8 |
| `--log-level` | `INFO` | уровень логирования |
| `--probe` | выкл. | дамп HTML для отладки |
| `--no-playwright` | выкл. | обход без браузера |

### 4.2. NewsSpider (SSR)

- Начальный URL формируется из `--domain` + `--start-path`.
- Блоки статей ищутся перебором `ARTICLE_SELECTORS` до первого совпадения —
  устойчивость к смене вёрстки.
- Поля: `title`, `url`, `date`, `author`, `summary`, `tags`, `source`.
- Пагинация: `a[rel=next]`, а также ссылки с текстом «Туда» / «Следующая» / «Next».
- Фильтрация по `--keywords` — по подстроке в `title + summary`, регистронезависимо.

### 4.3. EcommerceSpider (SPA)

- Запросы помечены `meta={"playwright": True}`.
- `PageMethod("wait_for_selector", …)` — ожидание появления карточек в DOM.
- `PageMethod("evaluate", "window.scrollTo(…)")` + пауза — подгрузка lazy-контента.
- Страница браузера закрывается в блоке `finally`, в том числе в `errback`.
- Поля: `title`, `url`, `price`, `rating`, `reviews_count`, `image_url`,
  `description`, `category`, `source`.
- Определены **оба** метода старта: `async def start()` (Scrapy 2.13+) и
  `start_requests()` (совместимость со старыми версиями).

### 4.4. Pipelines

| Приоритет | Класс | Действие | Реакция на брак |
|:---------:|-------|----------|-----------------|
| 100 | `CleaningPipeline` | `ftfy.fix_text`, схлопывание пробелов, обработка списков | — |
| 200 | `DuplicationPipeline` | `md5(url)` в `set` | `DropItem("дубликат")` |
| 300 | `ValidationPipeline` | обязательные поля по типу item | `DropItem("нет поля")` |

Обязательные поля: `NewsItem` → `title`, `url`;
`ProductItem` → `title`, `url`, `price`.

### 4.5. Обработка ошибок и retry

```python
RETRY_ENABLED = True
RETRY_TIMES = 3
RETRY_HTTP_CODES = [429, 500, 502, 503, 504]
DOWNLOAD_TIMEOUT = 30
DOWNLOAD_DELAY = 1.5
DOWNLOAD_DELAY_JITTER = 0.5
CONCURRENT_REQUESTS_PER_DOMAIN = 2
AUTOTHROTTLE_ENABLED = True
```

Дополнительно: `errback` на каждый запрос, проверка пустых селекторов с
логированием `WARNING`, `DropItem` на уровне pipelines.

### 4.6. Экспорт

`FEEDS` с `mode="overwrite"`, `encoding="utf-8"`; формат выбирается по
расширению `--output`. Остановка `CLOSESPIDER_ITEMCOUNT` считает записи,
прошедшие все pipelines.

---

## 5. Журнал выполнения и отладки

Работа выполнялась итеративно. Ниже — зафиксированные дефекты и их устранение.
Все диагнозы поставлены по статистике Scrapy из логов реальных запусков.

### Итерация 1 — исходная версия

| Паук | Наблюдение из лога | Диагноз |
|------|--------------------|---------|
| `news` | `item_dropped_count: 20`, во всех item `'title': None`; `downloader/response_status_count/200: 2` | селектор заголовка не совпадает с вёрсткой |
| `ecommerce` | `elapsed_time_seconds: 0.43`, нет `downloader/request_count` и `scheduler/enqueued` | запросы не создавались вовсе |

### Итерация 2 — добавлены fallback-селекторы и логирование

Лог `news` (Habr):
```
✅ Найдено статей по 'article': 20      × 11 страниц
→ Следующая страница: …/page2/ … /page12/
downloader/request_count: 11
depth/request_ignored_count: 1
request_depth_max: 10
feedexport/item_count: 0
```

Установлено **две** причины:

1. **Вложенный `<span>`.** Заголовок Habr — `<h2><a class="tm-title__link"><span>Текст</span></a></h2>`.
   В parsel `E::text` транслируется в `E/text()` (только прямые текстовые узлы),
   поэтому `h2 a::text` возвращает `None`. Требуется `h2 a ::text` → `E//text()`.
   Подтверждение: `url` и `author` извлекались корректно (атрибуты и прямой текст),
   а `title` — всегда `None`.
2. **`DEPTH_LIMIT = 10`** обрывал пагинацию на 12-й странице
   (`depth/request_ignored_count: 1`).

Лог `ecommerce` (DNS):
```
🌐 Домен: www.dns-shop.ru
Spider opened → Closing spider (finished)   (1.9 с)
статистика: нет downloader/*, нет scheduler/*
```
Сопоставление с `news` (где `start_urls` работал) показало: метод
`start_requests()` в Scrapy 2.20 не вызывается — он заменён на
`async def start()` начиная с 2.13. Также обнаружено, что `errback`,
переданный через `meta`, игнорируется — потому ошибок в логе не было.

### Итерация 3 — ошибка аргумента

```
Start URL: https://lenta.ru/test
Ignoring response <404 …>: HTTP status code is not handled
downloader/response_status_count/404: 1
```
Причина: передан несуществующий `--start-path "test"`. Дефект не в коде.

### Сводная таблица исправлений

| № | Дефект | Исправление |
|---|--------|-------------|
| 1 | `title = None` из-за вложенных тегов | все текстовые селекторы → ` ::text` + `.getall()` + склейка |
| 2 | 0 запросов у ecommerce | `async def start()` + `start_requests()` как fallback |
| 3 | ошибки запросов не логировались | `errback=` аргументом вместо `meta` |
| 4 | пагинация рвалась на page12 | `DEPTH_LIMIT = 0` |
| 5 | `$1,139.54` → `113954` | парсер цены с учётом разделителей `,` / `.` |
| 6 | счётчик в пауке не учитывал `DropItem` | `CLOSESPIDER_ITEMCOUNT` |
| 7 | лог нечитаем (UTF-16LE от PowerShell) | настройка `LOG_FILE` + `LOG_FILE_ENCODING="utf-8"` |
| 8 | warning `process_item() requires spider` | сигнатура `(self, item, *args, **kwargs)` |
| 9 | warning `RANDOMIZE_DOWNLOAD_DELAY` | `DOWNLOAD_DELAY_JITTER = 0.5` |
| 10 | warning `overwrite feed option` | `mode="overwrite"` |
| 11 | warning `MemUsage requires resource` | `MEMUSAGE_ENABLED = False` |
| 12 | сайты зашиты в код | `--domain` + `--start-path` |

---

## 6. Результаты

> Заполняется фактическими данными после итоговых запусков.
> Число записей получить командой `python check_data.py <файл>` либо из строки
> `записей в файле: N`, которую печатает `run_spider.py`.

### 6.1. Итоговые запуски

| № | Паук | Сайт (`--domain` / `--start-path`) | Формат | Файл | Записей | ≥ 100 |
|---|------|-----------------------------------|--------|------|:-------:|:-----:|
| 1 | `news` | ⟨habr.com / ru/articles/⟩ | JSON | `news.json` | 159 | ✅ |
| 3 | `ecommerce` | ⟨…⟩ | CSV | `products.csv` | ⟨N⟩ | ⟨✅/❌⟩ |

### 6.2. Статистика Scrapy (из `run.log`)

| Метрика | news | ecommerce |
|---------|:----:|:---------:|
| `downloader/request_count` | ⟨…⟩ | ⟨…⟩ |
| `downloader/response_status_count/200` | ⟨…⟩ | ⟨…⟩ |
| `item_scraped_count` | ⟨…⟩ | ⟨…⟩ |
| `item_dropped_count` | ⟨…⟩ | ⟨…⟩ |
| `retry/count` | ⟨…⟩ | ⟨…⟩ |
| `elapsed_time_seconds` | ⟨…⟩ | ⟨…⟩ |
| `finish_reason` | ⟨…⟩ | ⟨…⟩ |

### 6.3. Работа pipelines

| Pipeline | Обработано | Отброшено | Причина отбрасывания |
|----------|:----------:|:---------:|----------------------|
| `CleaningPipeline` | ⟨…⟩ | 0 | — |
| `DuplicationPipeline` | ⟨…⟩ | ⟨…⟩ | дубликат URL |
| `ValidationPipeline` | ⟨…⟩ | ⟨…⟩ | ⟨нет title / url / price⟩ |

### 6.4. Качество данных (`check_data.py`)

| Показатель | news | ecommerce |
|------------|:----:|:---------:|
| Записей | ⟨…⟩ | ⟨…⟩ |
| Пропусков по обязательным полям | ⟨…⟩ | ⟨…⟩ |
| Дубликатов по `url` | ⟨…⟩ | ⟨…⟩ |
| Дубликатов по `title` | ⟨…⟩ | ⟨…⟩ |
| Выбросов по `price` (IQR) | — | ⟨…⟩ |
| Медианная цена | — | ⟨…⟩ |

### 6.5. Примеры собранных записей

**NewsItem** (`news.json`):

```json
{
   "title": "Пока ИИ пишет код, кто-то должен держать продакшен: что изучать системному администратору", 
   "url": "https://habr.com/ru/companies/otus/articles/1112384/", 
   "date": "2026-11-27T07:05:19.000Z", 
   "author": "MaxRokatansky", 
   "summary": "Пока одни обсуждают, кого заменит ИИ, системным администраторам предстоит разбираться, как обеспечить работу всей этой инфраструктуры. Мы изучили актуальные требования работодателей, выделили ключевые направления профессионального развития сисадминов и предлагаем 23 практических разбора, которые помогут прокачать востребованные навыки и подготовиться к новым инженерным задачам.", 
   "tags": ["Системное администрирование", "*", "DevOps", "IT-инфраструктура"], 
   "source": "habr.com"
}
```

**ProductItem** (`products.csv`):

```csv
⟨вставить заголовок и 2–3 реальные строки⟩
```

---

## 7. Проверка выполнения требований

| № | Требование | Статус | Подтверждение |
|---|-----------|:------:|---------------|
| 1 | Два паука (SSR + SPA) | ⟨✅⟩ | `spiders/news.py`, `spiders/ecommerce.py` |
| 2 | ≥ 100 записей у `news` | ⟨✅/❌⟩ | §6.1, `check_data.py` |
| 2 | ≥ 100 записей у `ecommerce` | ⟨✅/❌⟩ | §6.1, `check_data.py` |
| 3 | `CleaningPipeline` (ftfy) | ⟨✅⟩ | `pipelines.py`, §4.4 |
| 3 | `DuplicationPipeline` | ⟨✅⟩ | §6.3, `item_dropped_count` |
| 3 | `ValidationPipeline` | ⟨✅⟩ | §6.3 |
| 4 | Retry 429/503 | ⟨✅⟩ | `RETRY_HTTP_CODES`, §4.5 |
| 4 | Логирование | ⟨✅⟩ | `run.log`, `self.logger` |
| 5 | CLI `--spider --keywords --output` | ⟨✅⟩ | §4.1, `--help` |
| 6 | Экспорт JSON и CSV | ⟨✅⟩ | §6.1 (оба формата) |
| 7 | Docker / Anti-Captcha / Redis | ➖ | опционально, исключено |

---

## 8. Ограничения работы

1. **Дедупликация в памяти.** Состояние живёт в рамках процесса; при
   распределённом запуске нужен внешний источник (Redis / Bloom filter).
2. **Зависимость от вёрстки.** Fallback-селекторы снижают, но не устраняют риск
   поломки после редизайна сайта. Требуется периодическая сверка через `--probe`.
3. **Антибот-защита.** Крупные маркетплейсы (Ozon, Wildberries, Citilink, DNS)
   блокируют автоматический доступ. Обход капчи не реализован по правовым
   причинам; для демонстрации использованы доступные сайты / учебные стенды.
4. **`lower()` не применяется** — сознательное решение ради сохранения имён
   собственных; при необходимости нормализуется на этапе анализа.
5. **Семантические дубликаты не выявляются.** Реализованы только точные
   (по URL). Нечёткие и семантические (`iPhone 14` ≈ `Айфон 14`) требуют
   RapidFuzz / эмбеддингов — за рамками работы.
6. **Выбросы только детектируются**, но не удаляются автоматически: по лекции
   аномальное значение может быть корректным.

---

## 9. Выводы

1. Реализована система сбора, покрывающая оба сценария из постановки:
   статический SSR (`NewsSpider`) и динамический SPA (`EcommerceSpider`
   с Playwright), с единым CLI и экспортом в JSON/CSV.
2. Полный конвейер предобработки (`Cleaning` → `Duplication` → `Validation`)
   обеспечивает воспроизводимое качество данных: битые кодировки исправляются,
   дубликаты и неполные записи отбрасываются с логированием причины.
3. Практически подтверждён тезис лекции о трудоёмкости этапа обработки:
   основная часть времени ушла не на написание пауков, а на **отладку
   извлечения и нормализации** — 12 зафиксированных дефектов (§5).
4. Ключевые технические уроки:
   - в parsel `E::text` ≠ `E ::text`: первый берёт только прямые текстовые
     узлы, второй — всех потомков; это самая частая причина «пустого title»;
   - Scrapy 2.13+ требует `async def start()`; `start_requests()` может
     молча не вызываться;
   - `errback` работает только как аргумент `Request`, не через `meta`;
   - счётчик внутри паука не равен числу сохранённых записей — корректный
     критерий останова `CLOSESPIDER_ITEMCOUNT`;
   - диагностика по статистике Scrapy (`downloader/request_count`,
     `item_dropped_count`, `depth/request_ignored_count`) позволяет точно
     локализовать дефект без угадывания.
5. Вынос домена и пути в CLI-аргументы сделал пауки универсальными: смена
   целевого сайта не требует правки кода, только подбора селекторов.

**Направления развития:** нечёткая дедупликация (RapidFuzz), хранение истории
снимков (версионность по лекции 1), Redis для распределённой очереди,
автотесты селекторов на сохранённых HTML-фикстурах.

---

## Приложение А. Команды воспроизведения

```bash
# Окружение
python -m venv .venv
.venv\Scripts\Activate.ps1            # Windows
pip install -r requirements.txt
playwright install chromium

# Запуск 1: новости → JSON
python run_spider.py --spider news --domain ⟨domain⟩ ^
  --start-path "⟨path⟩" --limit 120 --output news.json

# Запуск 2: новости → CSV
python run_spider.py --spider news --domain ⟨domain⟩ ^
  --start-path "⟨path⟩" --limit 120 --output news.csv

# Запуск 3: товары (Playwright) → CSV
python run_spider.py --spider ecommerce --domain ⟨domain⟩ ^
  --start-path "⟨path⟩" --limit 120 --output products.csv

# Запуск 4: товары → JSON
python run_spider.py --spider ecommerce --domain ⟨domain⟩ ^
  --start-path "⟨path⟩" --limit 120 --output products.json

# Контроль качества
python check_data.py news.json
python check_data.py products.csv

# Чтение лога
Get-Content run.log -Encoding UTF8 -Tail 60
```

---

## Приложение Б. Окружение

| Компонент | Версия |
|-----------|--------|
| ОС | Windows 11 (10.0.26300) |
| Python | 3.14.3 |
| Scrapy | 2.20.0 |
| scrapy-playwright | 0.0.48 |
| Playwright | 1.65.2 |
| parsel | 1.12.1 |
| lxml | 6.1.3 |
| Twisted | 26.10.0 |
| pyOpenSSL | 26.4.0 |

---

## Приложение В. Фрагменты логов

⟨вставить 10–20 строк из `run.log` итогового успешного запуска,
обязательно включить блок `Dumping Scrapy stats` с
`item_scraped_count` и `finish_reason`⟩

---

## Приложение Г. Состав сдаваемых файлов

```
webscraper/
├── scrapy.cfg
├── run_spider.py
├── requirements.txt
├── check_data.py
├── README.md
├── REPORT.md
├── news.json          ⟨результат⟩
├── news.csv           ⟨результат⟩
├── products.csv       ⟨результат⟩
├── products.json      ⟨результат⟩
├── run.log            ⟨лог⟩
└── webscraper/
    ├── items.py
    ├── pipelines.py
    ├── settings.py
    └── spiders/
        ├── news.py
        └── ecommerce.py
```