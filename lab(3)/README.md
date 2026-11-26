# 🌐 Wikimedia Data Collector

> Консольное приложение для автоматизированного сбора данных из экосистемы Wikimedia через MediaWiki API с адаптивным rate limiting и batch-запросами.

Лабораторная работа №3 по курсу «Интеллектуальный анализ веб-данных».  
Автоматизированный сборщик данных, взаимодействующий с основными проектами Wikimedia: **Википедия**, **Викиданные**, **Викисловарь** и **Wikimedia Commons**.

---

## 📋 Содержание

- [Описание](#-описание)
- [Возможности](#-возможности)
- [Требования](#-требования)
- [Установка](#-установка)
- [Настройка User-Agent](#-настройка-user-agent)
- [Использование](#-использование)
- [Примеры запуска](#-примеры-запуска)
- [Структура выходных данных](#-структура-выходных-данных)
- [Этикет API и rate limiting](#-этикет-api-и-rate-limiting)
- [Рендеринг графа](#-рендеринг-графа)
- [Диагностика Graphviz](#-диагностика-graphviz)
- [Архитектура](#-архитектура)
- [API-эндпоинты](#-api-эндпоинты)
- [Известные ограничения](#-известные-ограничения)
- [Диагностика](#-Диагностика)

---

## 🎯 Описание

Приложение принимает на вход запрос о **личности, объекте, событии, животном** и т.п., после чего:

1. Ищет соответствующую статью в Википедии
2. Получает связанные сущности из Викиданных
3. Извлекает определение из Викисловаря
4. Собирает изображения из Wikimedia Commons
5. Загружает **Picture of the Day** с описанием
6. Строит **граф связей** между статьями (минимум 30 узлов)
7. Сохраняет всё в единую JSON-структуру

---

## ✨ Возможности

| Возможность | Описание |
|-------------|----------|
| 🔍 Мульти-проектный сбор | Википедия (ru/en), Викиданные, Викисловарь, Commons |
| 🖼 Picture of the Day | Автоматическая загрузка картинки дня с описанием |
| 🕸 Граф связей | DOT + PDF с минимум 30 статьями, кликабельные узлы |
| 📦 JSON-экспорт | Полная структура узла + связанные узлы |
| 🎛 CLI-интерфейс | Гибкая настройка через `argparse` |
| 🐢 Этикет API | Адаптивные задержки между запросами |
| 🔄 Обработка rate limit | Подстройка задержки по `429` и `X-RateLimit-*` |
| 📋 Batch-запросы | Группировка до 50 `titles` за один HTTP-запрос |
| 🪪 User-Agent из файла | Загрузка идентификации из `User-Agent.json` |
| 🔒 Валидация PDF | Проверка сигнатуры `%PDF` / `%%EOF` после рендера |
| 🔗 Безопасные URL | Percent-encoding заголовков в атрибуте `URL` |

---

## 📦 Требования

### Системные

- **Python** 3.10+
- **Graphviz** с рендерером **cairo** — обязателен для `-Tpdf`

> ⚠️ Формат PDF в Graphviz доступен **только через cairo**. Проверить наличие:
> ```bash
> dot -Tpdf:cairo -V
> ```
> В выводе `-v` при рендере должно быть `Using device: pdf:cairo:cairo`.

### Python-зависимости

```
requests>=2.31.0
graphviz>=0.20.0
tqdm>=4.66.0
```

---

## 🪪 Настройка User-Agent

> ⚠️ Wikimedia Foundation требует информативный `User-Agent` с контактом. Без него бот может быть заблокирован без предупреждения.

### Формат файла `User-Agent.json`

```json
{
  "user_agent": "WikimediaLabBot/1.0 (student; course-web-mining; contact@example.com) python-requests/2.31",
  "email": "student@example.com",
  "project_url": "https://github.com/username/wikimedia-collector"
}
```

### Приоритет загрузки

1. Есть поле `user_agent` → используется напрямую
2. Нет → собирается из `email` + `project_url`
3. Файл не найден → дефолтный User-Agent + предупреждение в консоль

Файл читается **один раз** в `main()`, готовая строка передаётся во все экземпляры `MediaWikiAPI`.

### Кастомный путь

```bash
python wikimedia_collector.py "Менделеев" --user-agent-file ./config/my-agent.json
```

---

## 💻 Использование

```bash
python wikimedia_collector.py "ЗАПРОС" [ОПЦИИ]
python wikimedia_collector.py --help
```

| Опция | Описание | По умолчанию |
|-------|----------|--------------|
| `query` | Запрос (личность/объект/событие) | *обязательно* |
| `--lang {ru,en}` | Язык Википедии | `ru` |
| `--output FILE` | Базовое имя выходных файлов | `<query>` |
| `--graph / --no-graph` | Строить граф связей | `--graph` |
| `--min-articles N` | Мин. статей в графе | `30` |
| `--potd / --no-potd` | Загрузить Picture of the Day | `--potd` |
| `--potd-date YYYY-MM-DD` | Дата POTD | сегодня |
| `--potd-dir DIR` | Папка для POTD | `potd/` |
| `--timeout N` | Таймаут HTTP (сек) | `20` |
| `--user-agent-file FILE` | Путь к JSON с User-Agent | `User-Agent.json` |

---

## 🧪 Примеры запуска

```bash
# Базовый сбор
python wikimedia_collector.py "Дмитрий Менделеев"

# Кастомный User-Agent
python wikimedia_collector.py "Байкал" --user-agent-file ./config/my-agent.json

# Английская Википедия
python wikimedia_collector.py "Lake Baikal" --lang en

# Расширенный граф
python wikimedia_collector.py "Александр Пушкин" --min-articles 50

# POTD за конкретную дату
python wikimedia_collector.py "Эйнштейн" --potd-date 2024-01-15

# Только JSON
python wikimedia_collector.py "Кошка" --no-graph --no-potd

# Всё сразу
python wikimedia_collector.py "Москва" \
    --lang ru \
    --output moscow_data \
    --min-articles 40 \
    --potd-dir ./images/potd \
    --timeout 30 \
    --user-agent-file ./config/agent.json
```

---

## 📂 Структура выходных данных

```
.
├── <query>.json          # Основная JSON-структура
├── <query>.dot           # DOT-файл графа (сохраняется всегда)
├── <query>.pdf           # Отрендеренный граф
└── potd/
    ├── <filename>.jpg    # Picture of the Day
    └── <filename>.txt    # Описание (имя = имя картинки)
```

### Пример JSON

```json
{
  "query": "Дмитрий Менделеев",
  "timestamp": "2026-11-26T18:00:00",
  "wikipedia": {
    "pageid": 12345,
    "title": "Менделеев, Дмитрий Иванович",
    "extract": "Дми́трий Ива́нович Менделе́ев...",
    "links": ["Химия", "Периодический закон"],
    "images": ["File:Mendeleev.jpg"],
    "categories": ["Химики России"],
    "thumbnail": "https://...",
    "original_image": "https://..."
  },
  "wikidata": {
    "id": "Q9106",
    "labels": {"ru": "...", "en": "..."},
    "descriptions": {"ru": "..."},
    "claims": {"P31": ["Q5"], "P18": ["..."]},
    "sitelinks": {"ruwiki": "...", "enwiki": "..."},
    "commons_category": "Dmitry Mendeleev"
  },
  "wiktionary": {"title": "Менделеев", "definition": "..."},
  "commons": {"images": ["File:Mendeleev.jpg"]},
  "picture_of_the_day": {
    "date": "2026-11-26",
    "image_title": "File:Example.jpg",
    "local_file": "potd/Example.jpg",
    "description_file": "potd/Example.txt"
  },
  "graph_articles_count": 30,
  "graph_articles_titles": ["..."]
}
```

---

## 🐢 Этикет API и rate limiting

### Адаптивная задержка

| Событие | Реакция |
|---------|---------|
| Базовый интервал | `BASE_DELAY = 3.0` с между запросами |
| Успех (`200`) | задержка ×0.95, но не ниже `BASE_DELAY` |
| `429 Too Many Requests` | задержка ×1.5, максимум `10.0` с |
| `X-RateLimit-Remaining < 10` | предупреждение в stderr |
| `X-RateLimit-Remaining < 5` | задержка ×2, максимум `10.0` с |

### Повторы запросов

Декоратор `@retry_with_backoff` повторяет запрос при **сетевых исключениях** `requests.RequestException` (таймаут, обрыв соединения) с экспоненциальной задержкой: 3 → 6 → 12 → 24 → 48 с, до `MAX_RETRIES = 5` попыток.

> ℹ️ **Важно:** ответ `429` не приводит к автоматическому повтору — метод `request()` возвращает пустой `{}`, а адаптивная задержка увеличивается для следующих вызовов. Если нужен честный ретрай по `429`, обработку следует перенести внутрь `request()`.

### Batch-запросы

Сбор статей для графа идёт пачками до 50 `titles` за запрос (`titles=A|B|C|...`), что кратно снижает число обращений к API.

### Рекомендации

| Сценарий | Действие |
|----------|----------|
| Частые `429` | Поднять `BASE_DELAY` до `5.0`–`10.0` |
| Массовый сбор | Batch уже встроен, дополнительно ничего не нужно |
| Параллельные запросы | Не рекомендуются для Wikimedia API |

---

## 🕸 Рендеринг графа

### DOT сохраняется всегда

Даже если рендер недоступен или упал — `<query>.dot` остаётся на диске. Его можно открыть на [edotor.net](https://edotor.net/).

### URL обязательно в percent-encoding

Graphviz передаёт атрибут `URL` в cairo через **Tags & Links API** для создания PDF-аннотаций. **Сырая кириллица и пробелы в значении ломают cairo**, и на выходе получается нечитаемый PDF.

```python
from urllib.parse import quote

# ❌ НЕЛЬЗЯ — битый PDF
URL = f"https://ru.wikipedia.org/wiki/{title}"

# ✅ ПРАВИЛЬНО
URL = "https://ru.wikipedia.org/wiki/" + quote(title.replace(" ", "_"))
```

### Валидация результата

`dot` возвращает **код 0 даже при внутренней ошибке cairo**, поэтому проверять размер файла недостаточно. Проверяется сигнатура:

```python
data = pdf_path.read_bytes()
valid = data.startswith(b"%PDF-") and b"%%EOF" in data[-2048:]
```

### Переносы строк в label

Для многострочной надписи нужна escape-последовательность DOT `\n` — в Python это `"\\n"` или `r"\n"`. **Сырой символ перевода строки внутри кавычек DOT не предусмотрен спецификацией** и ломает часть парсеров (например, viz.js на edotor.net).

---

## 🩺 Диагностика Graphviz

Если PDF не открывается — не гадайте, запустите диагностику.

### `4debaging/check_graphviz.py`

Проверяет бинарь, доступные рендереры и валидность PDF на минимальном графе с кириллицей (через stdin→stdout, минуя файловые имена).

```bash
python 4debaging/check_graphviz.py
```

Ожидаемый вывод:

```
dot - graphviz version 16.1.1
Using device: pdf:cairo:cairo
заголовок: b'%PDF-1.7' | хвост: b'9\n%%EOF\n'
ВАЛИДНЫЙ PDF: True
```

### `4debaging/isolate_pdf.py`

Прогоняет 5 вариантов графа и показывает, какой именно ломается:

| Вариант | Что проверяет |
|---------|---------------|
| `V1_baseline` | граф без `URL` |
| `V2_URL_raw` | `URL` с сырой кириллицей и пробелами |
| `V3_URL_encoded` | `URL` в percent-encoding |
| `V4_raw_newline` | сырой `0x0A` внутри label |
| `V5_cyrillic_filename` | кириллическое имя файла |

**Типичный результат на Graphviz 16.x / Windows:**

```
V1_baseline      ВАЛИДЕН=True
V2_URL_raw       ВАЛИДЕН=False   ← cairo: invalid tag name, attributes, or nesting
V3_URL_encoded   ВАЛИДЕН=True
V4_raw_newline   ВАЛИДЕН=True
V5_cyrillic_filename ВАЛИДЕН=True
```

---

## 🏗 Архитектура

```
┌──────────────────────────────────────────────────────────┐
│                    CLI (argparse)                        │
│         --user-agent-file → User-Agent.json              │
└──────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────┐
│              MediaWikiAPI (HTTP-клиент)                  │
│  • requests.Session (connection pooling)                 │
│  • User-Agent, переданный извне                          │
│  • Адаптивная задержка (BASE_DELAY = 3.0)                │
│  • @retry_with_backoff (сетевые ошибки)                  │
│  • Проверка X-RateLimit-* заголовков                     │
│  • batch_request() — до 50 titles                        │
└──────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│  Wikipedia   │   │  Wikidata    │   │   Commons    │
│  (ru / en)   │   │  (entities)  │   │   (files)    │
└──────────────┘   └──────────────┘   └──────────────┘
        │                   │                   │
        └───────────────────┼───────────────────┘
                            ▼
                   ┌──────────────────┐
                   │  JSON Collector  │
                   └──────────────────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
        ┌──────────┐  ┌──────────┐  ┌──────────┐
        │ JSON out │  │ DOT/PDF  │  │  POTD    │
        └──────────┘  └──────────┘  └──────────┘
```

---

## 🌐 API-эндпоинты

| Проект | Endpoint |
|--------|----------|
| Википедия (RU) | `https://ru.wikipedia.org/w/api.php` |
| Википедия (EN) | `https://en.wikipedia.org/w/api.php` |
| Викиданные | `https://www.wikidata.org/w/api.php` |
| Викисловарь (RU) | `https://ru.wiktionary.org/w/api.php` |
| Wikimedia Commons | `https://commons.wikimedia.org/w/api.php` |

---

## ⚠️ Известные ограничения

- **PDF требует cairo** — без cairo-рендерера формат PDF недоступен.
- **`URL` только в percent-encoding** — иначе cairo ломает PDF при `exit=0`.
- **Rate limiting** — адаптивная задержка есть, автоповтора по `429` нет.
- **Граф может быть меньше 30 статей** — для узких запросов.
- **POTD не для всех дат** — шаблон может быть пуст.
- **User-Agent обязателен** — без корректного значения возможен бан.

---

## 🔧 Диагностика

### 🔴 PDF создаётся, но не открывается («Не удалось загрузить PDF-документ»)

**Симптом:** файл есть, размер нормальный (10–20 КБ), исключений при рендере нет.

**Причина:** не-ASCII символы или пробелы в атрибуте `URL`. В stderr при этом:

```
cairo: invalid tag name, attributes, or nesting
```

Graphviz отдаёт `URL` в cairo Tags & Links, cairo не может разобрать атрибуты, поверхность падает в ошибку — но **код возврата остаётся нулевым**.

**Решение:**

```python
URL = "https://ru.wikipedia.org/wiki/" + quote(title.replace(" ", "_"))
```

**Проверка:** запустите `tools/isolate_pdf.py`. Если `V2_URL_raw` битый, а `V3_URL_encoded` валиден — диагноз подтверждён.

> 💡 Смена шрифтов здесь **не помогает**. Предупреждение Pango `couldn't load font "DejaVu Sans Not-Rotated"` безвредно и присутствует во всех вариантах, включая рабочие.

---

### `Rate limit (429)`

1. Поднять `BASE_DELAY` до `5.0`–`10.0`
2. Проверить `User-Agent.json` — должен содержать контакт
3. Подождать несколько минут перед перезапуском

---

### `User-Agent.json not found`

Создать файл в корне проекта или указать путь через `--user-agent-file`.

---

### Граф меньше 30 статей

- Более общий запрос («Физика» вместо «Квантовая хромодинамика»)
- Снизить `--min-articles`
- Убедиться, что корневая статья существует

---

### `Permission denied` при перезаписи PDF

На Windows просмотрщик блокирует открытый файл. Закройте PDF перед повторным запуском или смените `--output`.

---
