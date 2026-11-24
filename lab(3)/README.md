# 🌐 Wikimedia Data Collector

> Консольное приложение для автоматизированного сбора данных из экосистемы Wikimedia через MediaWiki API с адаптивным rate limiting и batch-запросами.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)
![Status](https://img.shields.io/badge/status-stable-success)
![API](https://img.shields.io/badge/API-MediaWiki-orange)
![Rate Limit](https://img.shields.io/badge/rate%20limit-adaptive-yellow)

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
- [Архитектура](#-архитектура)
- [API-эндпоинты](#-api-эндпоинты)
- [Лицензия](#-лицензия)

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
| 🕸 Граф связей | DOT + PDF с минимум 30 статьями |
| 📦 JSON-экспорт | Полная структура узла + связанные узлы |
| 🎛 CLI-интерфейс | Гибкая настройка через `argparse` |
| 🐢 Этикет API | Автоматические задержки между запросами |
| 🔄 Адаптивный rate limiting | Экспоненциальный backoff при 429 + `Retry-After` |
| 📋 Batch-запросы | Группировка до 50 titles за один HTTP-запрос |
| 📊 Мониторинг rate limit | Проверка заголовков `X-RateLimit-*` |
| 🪪 User-Agent из файла | Загрузка идентификации из `User-Agent.json` |

---

## 📦 Требования

### Системные

- **Python** 3.10+
- **Graphviz** (системный пакет для рендеринга графа)

```bash
# Ubuntu / Debian
sudo apt install graphviz

# macOS
brew install graphviz

# Windows (Chocolatey)
choco install graphviz
```

### Python-зависимости

```
requests>=2.31.0
graphviz>=0.20.0
tqdm>=4.66.0
```

---

## 🚀 Установка

```bash
# 1. Клонируйте репозиторий
git clone https://github.com/your-username/wikimedia-collector.git
cd wikimedia-collector

# 2. Создайте виртуальное окружение
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# 3. Установите зависимости
pip install -r requirements.txt

# 4. Создайте файл User-Agent.json (см. следующий раздел)
cp User-Agent.json.example User-Agent.json
# Отредактируйте User-Agent.json под свои данные
```

**`requirements.txt`:**

```
requests>=2.31.0
graphviz>=0.20.0
tqdm>=4.66.0
```

---

## 🪪 Настройка User-Agent

> ⚠️ **Важно:** Wikimedia Foundation требует информативный `User-Agent` с контактом. Без него ваш бот может быть заблокирован без предупреждения.

### Формат файла `User-Agent.json`

Создайте в корне проекта файл **`User-Agent.json`**:

```json
{
  "user_agent": "WikimediaLabBot/1.0 (student; course-web-mining; contact@example.com) python-requests/2.31",
  "email": "student@example.com",
  "project_url": "https://github.com/username/wikimedia-collector"
}
```

### Приоритет загрузки

1. Если есть поле `user_agent` — используется оно напрямую
2. Если нет — собирается из `email` + `project_url`
3. Если файл не найден — используется дефолтный User-Agent с предупреждением

### Пример файла

```json
{
  "user_agent": "MyCourseBot/2.0 (https://github.com/student/wikimedia-collector; student@university.edu) python-requests/2.31"
}
```

### Кастомный путь к файлу

```bash
python wikimedia_collector.py "Менделеев" --user-agent-file ./config/my-agent.json
```

---

## 💻 Использование

### Базовый синтаксис

```bash
python wikimedia_collector.py "ЗАПРОС" [ОПЦИИ]
```

### Справка

```bash
python wikimedia_collector.py --help
```

### Основные опции

| Опция | Описание | По умолчанию |
|-------|----------|--------------|
| `query` | Запрос (личность/объект/событие) | *обязательно* |
| `--lang {ru,en}` | Язык Википедии | `ru` |
| `--output FILE` | Имя выходного JSON | `<query>.json` |
| `--graph / --no-graph` | Построить граф связей | `--graph` |
| `--min-articles N` | Мин. статей в графе | `30` |
| `--potd / --no-potd` | Загрузить Picture of the Day | `--potd` |
| `--potd-date YYYY-MM-DD` | Дата POTD | сегодня |
| `--potd-dir DIR` | Папка для POTD | `potd/` |
| `--timeout N` | Таймаут HTTP (сек) | `20` |
| `--user-agent-file FILE` | Путь к JSON с User-Agent | `User-Agent.json` |

---

## 🧪 Примеры запуска

### 1. Базовый сбор данных

```bash
python wikimedia_collector.py "Дмитрий Менделеев"
```

### 2. С кастомным User-Agent

```bash
python wikimedia_collector.py "Байкал" --user-agent-file ./config/my-agent.json
```

### 3. Английская Википедия с графом

```bash
python wikimedia_collector.py "Lake Baikal" --lang en --graph
```

### 4. Расширенный граф (50 статей)

```bash
python wikimedia_collector.py "Александр Пушкин" --min-articles 50
```

### 5. Picture of the Day за конкретную дату

```bash
python wikimedia_collector.py "Эйнштейн" --potd-date 2024-01-15
```

### 6. Только JSON, без графа и POTD

```bash
python wikimedia_collector.py "Кошка" --no-graph --no-potd
```

### 7. Полный пример со всеми параметрами

```bash
python wikimedia_collector.py "Москва" \
    --lang ru \
    --output moscow_data \
    --min-articles 40 \
    --potd \
    --potd-dir ./images/potd \
    --timeout 30 \
    --user-agent-file ./config/agent.json
```

---

## 📂 Структура выходных данных

После выполнения в текущей директории появятся:

```
.
├── <query>.json          # Основная JSON-структура
├── <query>.dot           # DOT-файл графа связей
├── <query>.pdf           # Отрендеренный граф
└── potd/
    ├── <filename>.jpg    # Picture of the Day
    └── <filename>.txt    # Описание картинки
```

### Пример JSON-структуры

```json
{
  "query": "Дмитрий Менделеев",
  "timestamp": "2026-11-24T12:00:00",
  "wikipedia": {
    "pageid": 12345,
    "title": "Менделеев, Дмитрий Иванович",
    "extract": "Дми́трий Ива́нович Менделе́ев...",
    "links": ["Химия", "Периодический закон", ...],
    "images": ["File:Mendeleev.jpg", ...],
    "categories": ["Химики России", ...],
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
  "wiktionary": {
    "title": "Менделеев",
    "definition": "..."
  },
  "commons": {
    "images": ["File:Mendeleev.jpg", ...]
  },
  "picture_of_the_day": {
    "date": "2026-11-24",
    "image_title": "File:Example.jpg",
    "local_file": "potd/Example.jpg",
    "description_file": "potd/Example.txt"
  },
  "graph_articles_count": 30,
  "graph_articles_titles": [...]
}
```

---

## 🐢 Этикет API и rate limiting

### Базовая задержка

Приложение использует **адаптивную задержку** между запросами:

- **Базовая задержка:** `3.0` секунды (`BASE_DELAY`)
- **При успехе (200):** задержка постепенно уменьшается (×0.9)
- **При rate limit (429):** задержка увеличивается (×1.5, макс. 10с)

### Экспоненциальный backoff

При получении HTTP 429:

1. Читается заголовок `Retry-After` (если есть)
2. Запрос повторяется до 5 раз (`MAX_RETRIES`)
3. Задержка растёт экспоненциально: 3с → 6с → 12с → ...

### Мониторинг rate limit

Клиент автоматически проверяет заголовки `X-RateLimit-*`:

- `X-RateLimit-Remaining` — сколько запросов осталось
- `X-RateLimit-Reset` — через сколько секунд сбросится лимит

При приближении к лимиту (< 10 запросов) — выводится предупреждение и увеличивается задержка.

### Batch-запросы

Для сбора графа статей используется **группировка запросов**:

- До 50 `titles` за один HTTP-запрос
- Формат: `titles=A|B|C|D|E`
- Значительно снижает нагрузку на API и ускоряет сбор

### Рекомендации

| Сценарий | Действие |
|----------|----------|
| Частые 429 ошибки | Увеличьте `BASE_DELAY` в коде до `5.0` |
| Массовый сбор (100+ статей) | Используйте batch-запросы (уже встроено) |
| Параллельные запросы | Не рекомендуется для Wikimedia API |

---

## 🏗 Архитектура

```
┌──────────────────────────────────────────────────────────┐
│                    CLI (argparse)                         │
│         --user-agent-file → User-Agent.json               │
└──────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────┐
│              MediaWikiAPI (HTTP-клиент)                   │
│  ┌────────────────────────────────────────────────────┐  │
│  │ • requests.Session (connection pooling)            │  │
│  │ • User-Agent из JSON-файла                         │  │
│  │ • Адаптивная задержка (BASE_DELAY = 3.0)           │  │
│  │ • @retry_with_backoff (экспоненциальный backoff)   │  │
│  │ • Проверка X-RateLimit-* заголовков                │  │
│  │ • batch_request() — группировка до 50 titles       │  │
│  └────────────────────────────────────────────────────┘  │
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

📚 **Полезные ссылки:**
- [API: Учебное пособие — MediaWiki](https://www.mediawiki.org/wiki/API:Tutorial/ru)
- [API Portal](https://www.mediawiki.org/wiki/API:Main_page/ru)
- [Песочница API](https://ru.wikipedia.org/wiki/Special:ApiSandbox)
- [API Etiquette](https://www.mediawiki.org/wiki/API:Etiquette)

---

## ⚠️ Известные ограничения

- **Rate limiting** — API Wikimedia ограничивает частоту запросов. В коде предусмотрена адаптивная задержка `3.0с` между запросами + экспоненциальный backoff при 429.
- **Граф может быть меньше 30 статей** — для узких запросов. Используйте `--min-articles` с меньшим значением или более общие запросы.
- **POTD не для всех дат** — шаблон `Template:POTD_protected` может быть пуст для некоторых дней.
- **JS-рендеринг** — приложение работает только со статическими API-ответами (для Wikimedia это не проблема).
- **User-Agent обязателен** — без корректного User-Agent Wikimedia может заблокировать доступ.

---

## 🔧 Troubleshooting

### Ошибка: `Rate limit (429)`

**Решение:**
1. Увеличьте `BASE_DELAY` в коде до `5.0` или `10.0`
2. Проверьте `User-Agent.json` — он должен содержать информативный User-Agent
3. Подождите несколько минут перед повторным запуском

### Ошибка: `User-Agent.json not found`

**Решение:**
1. Создайте файл `User-Agent.json` в корне проекта
2. Или укажите путь через `--user-agent-file ./path/to/agent.json`

### Граф меньше 30 статей

**Решение:**
1. Используйте более общий запрос (например, "Физика" вместо "Квантовая хромодинамика")
2. Снизьте `--min-articles` до 20 или 15
3. Проверьте, что корневая статья существует в Википедии

