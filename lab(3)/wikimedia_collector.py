#!/usr/bin/env python3
"""
Лабораторная работа №3: Сборщик данных из проектов Wikimedia.

Взаимодействует через MediaWiki API с:
  - Википедией (ru/en)
  - Викиданными
  - Викисловарём
  - Wikimedia Commons

На вход: запрос о личности/объекте/событии/животном.
На выход: JSON со структурой узла + связанные узлы + граф DOT.
Дополнительно: Picture of the Day (POTD) с описанием.
"""

import argparse
from functools import wraps
import json
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import unquote, quote
import subprocess

import requests
from tqdm import tqdm

try:
    import graphviz
    from graphviz import escape
except ImportError:
    graphviz = None
    escape = None


# ============================================================
#region Константы
# ============================================================
API_ENDPOINTS = {
    "wikipedia_ru": "https://ru.wikipedia.org/w/api.php",
    "wikipedia_en": "https://en.wikipedia.org/w/api.php",
    "wikidata": "https://www.wikidata.org/w/api.php",
    "wiktionary_ru": "https://ru.wiktionary.org/w/api.php",
    "commons": "https://commons.wikimedia.org/w/api.php",
}

DEFAULT_USER_AGENT = (
    "WikimediaLabBot/1.0 (student; course-web-mining) "
    "python-requests/2.31"
)

# Задержка между запросами (этикет API Wikimedia)
BASE_DELAY = 3.0 # выбрано задержка в 3 с из-за частых "Rate limiting"
MAX_RETRIES = 5
# ============================================================
#endregion Константы
# ============================================================

def load_user_agent(file_path: str = "User-Agent.json") -> str:
    """
    Загружает User-Agent из JSON-файла.
    Формат файла:
    {
        "user_agent": "BotName/1.0 (contact; email@example.com)",
        "email": "email@example.com",
        "project_url": "https://..."
    }
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # Приоритет: user_agent > составной из email + project_url
        if "user_agent" in data:
            return data["user_agent"]
        
        # Если нет готового user_agent — собираем из компонентов
        email = data.get("email", "unknown@example.com")
        project_url = data.get("project_url", "https://example.com")
        return f"WikimediaLabBot/1.0 ({project_url}; {email}) python-requests/2.31"
    
    except FileNotFoundError:
        print(
            f"⚠️  Файл {file_path} не найден. Использую дефолтный User-Agent.",
            file=sys.stderr
        )
        return "WikimediaLabBot/1.0 (student; course-web-mining) python-requests/2.31"
    except json.JSONDecodeError as e:
        print(
            f"⚠️  Ошибка парсинга {file_path}: {e}. Использую дефолтный User-Agent.",
            file=sys.stderr
        )
        return "WikimediaLabBot/1.0 (student; course-web-mining) python-requests/2.31"

def retry_with_backoff(func):
    """Декоратор: повторяет запрос при 429 с растущей задержкой."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        delay = BASE_DELAY
        for attempt in range(MAX_RETRIES):
            try:
                response = func(*args, **kwargs)
                # Если это уже dict (результат запроса) — возвращаем как есть
                if isinstance(response, dict):
                    return response
                # Если это Response объект — проверяем статус
                if hasattr(response, 'status_code'):
                    if response.status_code == 200:
                        return response
                    if response.status_code == 429:
                        retry_after = int(
                            response.headers.get("Retry-After", delay * 2)
                        )
                        print(
                            f"  ⏳ Rate limit (429). Ждём {retry_after}с "
                            f"(попытка {attempt + 1}/{MAX_RETRIES})"
                        )
                        time.sleep(retry_after)
                        continue
                    response.raise_for_status()
                    return response
                return response
                
            except requests.RequestException as e:
                print(f"  [!] Ошибка: {e}. Ждём {delay}с")
                time.sleep(delay)
                delay *= 2  # экспоненциальный рост
        
        raise RuntimeError(f"Не удалось выполнить запрос после {MAX_RETRIES} попыток")
    return wrapper

# ============================================================
#region 1. CLI-парсер
# ============================================================
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Сборщик данных из проектов Wikimedia через MediaWiki API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Примеры:\n"
            "  python wikimedia_collector.py \"Дмитрий Менделеев\"\n"
            "  python wikimedia_collector.py \"Байкал\" --lang en --graph\n"
            "  python wikimedia_collector.py \"Кошка\" --no-potd\n"
            "  python wikimedia_collector.py \"Пушкин\" --min-articles 50\n"
        ),
    )
    parser.add_argument(
        "query",
        help="Запрос: имя личности, объекта, события, животного и т.п.",
    )
    parser.add_argument(
        "--lang",
        choices=["ru", "en"],
        default="ru",
        help="Язык Википедии для основного поиска (по умолчанию ru)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Имя выходного JSON-файла (по умолчанию: query.json)",
    )
    parser.add_argument(
        "--graph/--no-graph",
        dest="graph",
        default=True,
        help="Построить граф связей в формате DOT (по умолчанию ДА)",
    )
    parser.add_argument(
        "--min-articles",
        type=int,
        default=30,
        help="Минимальное число статей в графе (по требованию — 30)",
    )
    parser.add_argument(
        "--potd/--no-potd",
        dest="potd",
        default=True,
        help="Получить картинку дня Picture of the Day (по умолчанию ДА)",
    )
    parser.add_argument(
        "--potd-date",
        default=None,
        help="Дата POTD в формате YYYY-MM-DD (по умолчанию — сегодня)",
    )
    parser.add_argument(
        "--potd-dir",
        default="potd",
        help="Папка для сохранения картинки дня (по умолчанию potd/)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=20,
        help="Таймаут HTTP-запроса в секундах (по умолчанию 20)",
    )
    parser.add_argument(
        "--user-agent-file",
        default="User-Agent.json",
        help="Путь к JSON-файлу с User-Agent (по умолчанию User-Agent.json)",
    )
    return parser
# ============================================================
#endregion 1. CLI-парсер
# ============================================================

# ============================================================
#region 2. HTTP-клиент
# ============================================================
class MediaWikiAPI:
    """Обёртка над MediaWiki API с учётом этикета."""
    
    def __init__(self, endpoint: str, timeout: int = 20, user_agent: str = DEFAULT_USER_AGENT):
        self.endpoint = endpoint
        self.timeout = timeout
        self.session = requests.Session()
        
        self.session.headers.update({"User-Agent": user_agent})
        
        # Для адаптивной задержки
        self._last_request_time = 0
        self._min_delay = BASE_DELAY
        
        # Статистика rate limit
        self._rate_limit_remaining = None
        self._rate_limit_reset = None

    def _check_rate_limit_headers(self, response: requests.Response) -> None:
        """
        Проверяет заголовки X-RateLimit-* и предупреждает о приближении к лимиту.
        MediaWiki API возвращает:
        - X-RateLimit-Remaining: сколько запросов осталось
        - X-RateLimit-Reset: через сколько секунд сбросится лимит
        """
        remaining = response.headers.get("X-RateLimit-Remaining")
        reset = response.headers.get("X-RateLimit-Reset")
        
        if remaining is not None:
            self._rate_limit_remaining = int(remaining)
            if self._rate_limit_remaining < 10:
                print(
                    f"  ⚠️  Rate limit: осталось {self._rate_limit_remaining} запросов",
                    file=sys.stderr
                )
                # Увеличиваем задержку если близко к лимиту
                if self._rate_limit_remaining < 5:
                    self._min_delay = min(self._min_delay * 2.0, 10.0)
        
        if reset is not None:
            self._rate_limit_reset = int(reset)

    @retry_with_backoff
    def request(self, params: dict) -> dict:
        """Запрос с адаптивной задержкой между вызовами."""
        # Соблюдаем минимальный интервал между запросами
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_delay:
            time.sleep(self._min_delay - elapsed)

        params.setdefault("format", "json")
        resp = self.session.get(
            self.endpoint, params=params, timeout=self.timeout
        )
        self._last_request_time = time.time()
        
        # Проверяем rate limit заголовки
        self._check_rate_limit_headers(resp)

        # Динамическая подстройка задержки
        if resp.status_code == 429:
            self._min_delay = min(self._min_delay * 1.5, 10.0)
        elif resp.status_code == 200 and self._min_delay > BASE_DELAY:
            # Постепенно уменьшаем задержку при успехе
            self._min_delay = max(self._min_delay * 0.95, BASE_DELAY)

        return resp.json() if resp.status_code == 200 else {}

    def batch_request(self, titles: list[str], base_params: dict) -> dict:
        """
        Группирует запросы: передаёт несколько titles за раз (до 50).
        MediaWiki API поддерживает: titles=A|B|C|D|E
        """
        # Разбиваем на чанки по 50 (лимит MediaWiki)
        chunk_size = 50
        all_results = {}
        
        for i in range(0, len(titles), chunk_size):
            chunk = titles[i:i + chunk_size]
            titles_str = "|".join(chunk)
            
            params = base_params.copy()
            params["titles"] = titles_str
            
            data = self.request(params)
            
            # Объединяем результаты
            pages = data.get("query", {}).get("pages", {})
            all_results.update(pages)
        
        return {"query": {"pages": all_results}}

# ============================================================
#endregion 2. HTTP-клиент
# ============================================================

# ============================================================
#region 3. Википедии
# ============================================================
def fetch_wikipedia_article(
    api: MediaWikiAPI, title: str, lang: str = "ru"
) -> dict:
    """
    Получает статью Википедии: текст, ссылки, изображения, категории.
    Использует action=query с prop=extracts|links|images|categories|pageimages.
    """
    params = {
        "action": "query",
        "titles": title,
        "prop": "extracts|links|images|categories|pageimages",
        "explaintext": 1,           # plain text без HTML
        "exintro": 0,               # вся статья, не только введение
        "pllimit": "500",           # максимум ссылок за запрос
        "imlimit": "100",           # максимум изображений
        "cllimit": "100",           # максимум категорий
        "piprop": "original|thumbnail",
        "pithumbsize": 400,
        "redirects": 1,             # следовать редиректам
    }
    data = api.request(params)
    pages = data.get("query", {}).get("pages", {})
    if not pages:
        return {}

    page = next(iter(pages.values()))
    if page.get("missing") == "":
        return {}

    return {
        "pageid": page.get("pageid"),
        "title": page.get("title"),
        "lang": lang,
        "extract": page.get("extract", ""),
        "links": [p["title"] for p in page.get("links", [])],
        "images": [p["title"] for p in page.get("images", [])],
        "categories": [p["title"] for p in page.get("categories", [])],
        "thumbnail": page.get("thumbnail", {}).get("source"),
        "original_image": page.get("original", {}).get("source"),
    }

def search_wikipedia(api: MediaWikiAPI, query: str) -> str | None:
    """Ищет статью в Википедии по запросу, возвращает точное название."""
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": 1,
    }
    data = api.request(params)
    results = data.get("query", {}).get("search", [])
    if not results:
        return None
    return results[0]["title"]
# ============================================================
#endregion 3. Википедии
# ============================================================

# ============================================================
#region 4.  Викиданных
# ============================================================
def fetch_wikidata_entity(api: MediaWikiAPI, title: str, lang: str) -> dict:
    """
    Получает сущность Wikidata по названию статьи Википедии.
    Использует wbgetentities с sites+titles.
    """
    site = f"{lang}wiki"
    params = {
        "action": "wbgetentities",
        "sites": site,
        "titles": title,
        "props": "labels|descriptions|claims|sitelinks",
        "languages": f"{lang}|en",
    }
    data = api.request(params)
    entities = data.get("entities", {})
    if not entities:
        return {}

    entity = next(iter(entities.values()))
    if entity.get("missing") == "":
        return {}

    # Извлекаем labels и descriptions
    labels = {
        k: v.get("value") for k, v in entity.get("labels", {}).items()
    }
    descriptions = {
        k: v.get("value") for k, v in entity.get("descriptions", {}).items()
    }

    # Извлекаем ключевые claims (P31 — instance of, P279 — subclass of)
    claims = {}
    for prop_id in ["P31", "P279", "P18", "P373"]:
        if prop_id in entity.get("claims", {}):
            values = []
            for claim in entity["claims"][prop_id]:
                mainsnak = claim.get("mainsnak", {})
                datavalue = mainsnak.get("datavalue", {})
                if datavalue.get("type") == "wikibase-entityid":
                    values.append(datavalue["value"]["id"])
                elif datavalue.get("type") == "string":
                    values.append(datavalue["value"])
            claims[prop_id] = values

    # Sitelinks — ссылки на статьи в разных языковых разделах
    sitelinks = {
        k: v.get("title") for k, v in entity.get("sitelinks", {}).items()
    }

    return {
        "id": entity.get("id"),
        "labels": labels,
        "descriptions": descriptions,
        "claims": claims,
        "sitelinks": sitelinks,
        "commons_category": claims.get("P373", [None])[0],
        "image_claim": claims.get("P18", [None])[0],
    }
# ============================================================
#endregion 4.  Викиданных
# ============================================================

# ============================================================
#region 5. Викисловаря
# ============================================================
def fetch_wiktionary(api: MediaWikiAPI, title: str) -> dict:
    """Получает определение из Викисловаря (action=parse)."""
    params = {
        "action": "parse",
        "page": title,
        "prop": "text",
        "formatversion": 2,
    }
    data = api.request(params)
    if "error" in data or "parse" not in data:
        return {}

    html = data["parse"].get("text", "")
    # Грубая очистка HTML для получения текста
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    # Берём первые 1000 символов
    return {
        "title": title,
        "definition": text[:1000],
    }
# ============================================================
#endregion 5. Викисловаря
# ============================================================

# ============================================================
#region 6. Wikimedia Commons
# ============================================================
def fetch_commons_images(api: MediaWikiAPI, title: str, category: str = None) -> dict:
    """
    Получает изображения из Commons.
    Если указан category — ищет в категории, иначе — по названию файла.
    """
    images = []

    if category:
        # Поиск в категории
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": f"Category:{category}",
            "cmtype": "file",
            "cmlimit": 20,
        }
        data = api.request(params)
        for member in data.get("query", {}).get("categorymembers", []):
            images.append(member.get("title"))
    else:
        # Поиск по названию
        params = {
            "action": "query",
            "titles": f"File:{title}.jpg",
            "prop": "imageinfo",
            "iiprop": "url|size|mime",
        }
        data = api.request(params)
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            if page.get("missing") != "":
                for ii in page.get("imageinfo", []):
                    images.append({
                        "title": page.get("title"),
                        "url": ii.get("url"),
                        "size": ii.get("size"),
                        "mime": ii.get("mime"),
                    })

    return {"images": images}
# ============================================================
#endregion 6. Wikimedia Commons
# ============================================================

# ============================================================
#region 7. Picture of the Day
# ============================================================
def fetch_picture_of_the_day(
    api: MediaWikiAPI, target_date: date, save_dir: Path
) -> dict:
    """
    Получает картинку дня из английской Википедии.
    Пример из презентации лекции: Template:POTD_protected/YYYY-MM-DD.
    Сохраняет картинку + текстовый файл с описанием рядом.
    """
    date_iso = target_date.isoformat()
    template_title = f"Template:POTD_protected/{date_iso}"

    # Получаем изображения из шаблона (пример из презентации)
    params = {
        "action": "parse",
        "page": template_title,
        "prop": "images|text",
        "formatversion": 2,
    }
    data = api.request(params)

    if "error" in data:
        print(f"  [!] POTD не найден для {date_iso}", file=sys.stderr)
        return {}

    images = data.get("parse", {}).get("images", [])
    html_text = data.get("parse", {}).get("text", "")

    if not images:
        print(f"  [!] Нет изображений в POTD для {date_iso}", file=sys.stderr)
        return {}

    # Берём первое изображение (обычно это и есть POTD)
    image_title = images[0]
    if not image_title.startswith("File:"):
        image_title = f"File:{image_title}"

    # Получаем URL изображения через imageinfo
    params = {
        "action": "query",
        "titles": image_title,
        "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata",
    }
    data = api.request(params)
    pages = data.get("query", {}).get("pages", {})
    page = next(iter(pages.values()), {})
    imageinfo = page.get("imageinfo", [{}])[0]

    image_url = imageinfo.get("url")
    if not image_url:
        return {}

    # Метаданные для описания
    extmeta = imageinfo.get("extmetadata", {})
    description = (
        extmeta.get("ImageDescription", {}).get("value")
        or extmeta.get("ObjectName", {}).get("value")
        or image_title
    )
    description = re.sub(r"<[^>]+>", "", description).strip()
    artist = extmeta.get("Artist", {}).get("value", "")
    artist = re.sub(r"<[^>]+>", "", artist).strip()
    license_name = extmeta.get("LicenseShortName", {}).get("value", "")

    # Скачиваем изображение
    save_dir.mkdir(parents=True, exist_ok=True)
    # Имя файла = имя картинки (как в задании)
    filename = image_title.replace("File:", "").replace(" ", "_")
    image_path = save_dir / filename
    # Текстовый файл — с тем же именем, но .txt
    text_path = save_dir / (image_path.stem + ".txt")

    try:
        resp = requests.get(image_url, timeout=30, stream=True)
        resp.raise_for_status()
        with open(image_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"  ✅ Изображение сохранено: {image_path}")
    except Exception as e:
        print(f"  [!] Ошибка загрузки изображения: {e}", file=sys.stderr)
        return {}

    # Сохраняем описание в текстовый файл рядом с картинкой
    description_text = (
        f"Picture of the Day — {date_iso}\n"
        f"{'=' * 60}\n\n"
        f"File: {filename}\n"
        f"Source: {image_url}\n"
        f"Date: {date_iso}\n\n"
        f"Description:\n{description}\n\n"
        f"Artist: {artist}\n"
        f"License: {license_name}\n"
    )
    text_path.write_text(description_text, encoding="utf-8")
    print(f"  ✅ Описание сохранено: {text_path}")

    return {
        "date": date_iso,
        "image_title": image_title,
        "image_url": image_url,
        "local_file": str(image_path),
        "description_file": str(text_path),
        "description": description,
        "artist": artist,
        "license": license_name,
    }
# ============================================================
#endregion 7. Picture of the Day
# ============================================================

# ============================================================
#region 8. Построение графа связей
# ============================================================
def build_graph(
    root_title: str,
    articles: list[dict],
    min_articles: int,
    output_base: str,
) -> None:
    """
    Строит граф связей между статьями.
    Узлы — статьи, рёбра — гиперссылки между ними.
    Требование: минимум min_articles статей (по умолчанию 30).
    """
    if graphviz is None:
        print("  [!] graphviz не установлен — граф не построен", file=sys.stderr)
        return
    
    # Проверка наличия системного graphviz
    import shutil
    if shutil.which("dot") is None:
        print(
            "  [!] Системный graphviz (бинарь 'dot') не найден. "
            "Установите: apt install graphviz / choco install graphviz / brew install graphviz",
            file=sys.stderr
        )
        print("  ℹ️  DOT-файл будет сохранён, но PDF не будет отрендерен.")
        render_pdf = False
    else:
        render_pdf = True
    
    if len(articles) < min_articles:
        print(
            f"  ⚠️  В графе только {len(articles)} статей. "
            f"Требуется минимум {min_articles}. "
            f"Попробуйте расширить запрос или снизить --min-articles.",
            file=sys.stderr,
        )
    
    # Определяем шрифт с поддержкой кириллицы
    font_name = "Arial" 
    
    dot = graphviz.Digraph(
        name="WikimediaGraph",
        comment=f"Граф связей: {root_title}",
        format="pdf",
    )
    
    # КРИТИЧНО: указываем charset и fontname для поддержки кириллицы
    dot.attr(
        rankdir="LR",
        label=f"Граф связей Wikimedia: {root_title}; Статей: {len(articles)}",
        labelloc="t",
        fontsize="16",
        fontname=font_name,
        charset="UTF-8",  # Явно указываем UTF-8
    )
    
    # Узлы с шрифтом, поддерживающим кириллицу
    dot.attr("node", 
             shape="box", 
             style="filled", 
             fillcolor="lightyellow",
             fontname=font_name,
             fontsize="10")
    
    # Рёбра с тем же шрифтом
    dot.attr("edge", 
             color="gray60",
             fontname=font_name,
             fontsize="8")
    
    # Множество названий для быстрого поиска
    known_titles = {a["title"] for a in articles}
    
    # Добавляем узлы
    for a in articles:
        is_root = a["title"] == root_title
        color = "gold" if is_root else "lightyellow"
        dot.node(
            a["title"],
            label=a["title"],
            fillcolor=color,
            # Кириллица/пробелы в URL ломают cairo Tags & Links:
            # PDF получается битым при exit=0. Кодируем в percent-encoding.
            URL="https://ru.wikipedia.org/wiki/" + quote(a["title"].replace(" ", "_")),
        )
    
    # Добавляем рёбра (только между известными статьями)
    edges_count = 0
    for a in articles:
        for link in a.get("links", []):
            if link in known_titles and link != a["title"]:
                dot.edge(a["title"], link)
                edges_count += 1
    
    # Сохраняем DOT-файл
    dot_path = Path(f"{output_base}.dot")
    dot_path.write_text(dot.source, encoding="utf-8")
    print(f"💾 DOT-файл графа сохранён: {dot_path}")
    
    # Рендерим в PDF
    if render_pdf:
        try:
            rendered = dot.render(filename=output_base, cleanup=True)
            print(f"🖼  Граф отрендерен: {rendered}")
            
            # Проверяем, что файл не пустой
            pdf_path = Path(f"{output_base}.pdf")
            if pdf_path.exists():
                data = pdf_path.read_bytes()
                # dot отдаёт exit=0 даже при ошибке cairo — проверяем байты
                if data.startswith(b"%PDF-") and b"%%EOF" in data[-2048:]:
                    print(f"  ✅ PDF валиден: {pdf_path} ({len(data)} байт)")
                else:
                    print(
                        f"  [!] PDF битый ({len(data)} байт). "
                        f"Причина — в stderr выше (ищи строку 'cairo:').",
                        file=sys.stderr
                    )
                
        except Exception as e:
            print(f"  [!] Ошибка рендеринга графа: {e}", file=sys.stderr)
            print(f"  ℹ️  DOT-файл сохранён: {dot_path}")
            print(f"  💡 Попробуйте открыть DOT-файл в онлайн-редакторе: https://edotor.net/")
    else:
        print("ℹ️  PDF не отрендерен (системный graphviz отсутствует)")
    
    print(f"📊 Граф: {len(articles)} узлов, {edges_count} рёбер")
    
def collect_articles_for_graph(
    api_ru: MediaWikiAPI,
    root_title: str,
    min_articles: int,
) -> list[dict]:
    """
    Собирает статьи для графа: корневая + её ссылки + ссылки на ссылки.
    Использует batch-запросы для ускорения.
    Останавливается при достижении min_articles.
    """
    articles = []
    visited = set()
    queue = [root_title]
    
    # Буфер для batch-запросов
    batch_buffer = []
    BATCH_SIZE = 50  # MediaWiki лимит

    with tqdm(total=min_articles, desc="Сбор статей для графа") as pbar:
        while queue and len(articles) < min_articles:
            # Собираем батч
            while queue and len(batch_buffer) < BATCH_SIZE and len(articles) + len(batch_buffer) < min_articles:
                title = queue.pop(0)
                if title not in visited:
                    visited.add(title)
                    batch_buffer.append(title)
            
            if not batch_buffer:
                break
            
            # Batch-запрос: получаем несколько статей за раз
            base_params = {
                "action": "query",
                "prop": "extracts|links|images|categories|pageimages",
                "explaintext": 1,
                "exintro": 0,
                "pllimit": "100",  # Уменьшаем для batch
                "imlimit": "50",
                "cllimit": "50",
                "piprop": "original|thumbnail",
                "pithumbsize": 400,
                "redirects": 1,
            }
            
            data = api_ru.batch_request(batch_buffer, base_params)
            pages = data.get("query", {}).get("pages", {})
            
            # Обрабатываем результаты
            for page_id, page in pages.items():
                if page.get("missing") == "":
                    continue
                
                article = {
                    "pageid": page.get("pageid"),
                    "title": page.get("title"),
                    "lang": "ru",
                    "extract": page.get("extract", ""),
                    "links": [p["title"] for p in page.get("links", [])],
                    "images": [p["title"] for p in page.get("images", [])],
                    "categories": [p["title"] for p in page.get("categories", [])],
                    "thumbnail": page.get("thumbnail", {}).get("source"),
                    "original_image": page.get("original", {}).get("source"),
                }
                
                articles.append(article)
                pbar.update(1)
                
                # Добавляем ссылки в очередь
                if len(articles) < min_articles:
                    for link in article.get("links", [])[:10]:  # Ограничиваем
                        if link not in visited:
                            queue.append(link)
            
            # Очищаем буфер
            batch_buffer = []
    
    return articles

# ============================================================
#endregion 8. Построение графа связей
# ============================================================

# ============================================================
#region Main
# ============================================================
def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    user_agent = load_user_agent(args.user_agent_file)
    
    output_name = args.output or re.sub(r"[^\w\-_]", "_", args.query)
    output_json = Path(f"{output_name}.json")

    print(f"🔎 Запрос: {args.query}")
    print(f"🌐 Язык Википедии: {args.lang}")
    print(f"📊 Мин. статей в графе: {args.min_articles}")
    print(f"🖼  POTD: {'ДА' if args.potd else 'НЕТ'}")
    print(f"📁 Выходной файл: {output_json}")
    print("─" * 60)

    # API-клиенты
    api_ru = MediaWikiAPI(
        API_ENDPOINTS["wikipedia_ru"], 
        args.timeout,
        user_agent=user_agent  
    )
    api_en = MediaWikiAPI(
        API_ENDPOINTS["wikipedia_en"], 
        args.timeout,
        user_agent=user_agent  
    )
    api_wd = MediaWikiAPI(
        API_ENDPOINTS["wikidata"], 
        args.timeout,
        user_agent=user_agent  
    )
    api_wt = MediaWikiAPI(
        API_ENDPOINTS["wiktionary_ru"], 
        args.timeout,
        user_agent=user_agent  
    )
    api_cm = MediaWikiAPI(
        API_ENDPOINTS["commons"], 
        args.timeout,
        user_agent=user_agent  
    )

    result = {"query": args.query, "timestamp": datetime.now().isoformat()}

    # ── Поиск статьи в Википедии ──
    print("\n📖 Шаг 1: Поиск статьи в Википедии...")
    main_api = api_ru if args.lang == "ru" else api_en
    title = search_wikipedia(main_api, args.query)
    if not title:
        print(f"❌ Статья не найдена по запросу: {args.query}", file=sys.stderr)
        return 1
    print(f"  ✅ Найдена статья: {title}")

    # ── Получение статьи Википедии ──
    print("\n📄 Шаг 2: Получение статьи Википедии...")
    wikipedia_data = fetch_wikipedia_article(main_api, title, args.lang)
    result["wikipedia"] = wikipedia_data
    print(
        f"  ✅ Ссылок: {len(wikipedia_data.get('links', []))}, "
        f"изображений: {len(wikipedia_data.get('images', []))}"
    )

    # ── Викиданные ──
    print("\n🔗 Шаг 3: Получение данных из Wikidata...")
    wikidata = fetch_wikidata_entity(api_wd, title, args.lang)
    result["wikidata"] = wikidata
    if wikidata:
        print(f"  ✅ ID сущности: {wikidata.get('id')}")
    else:
        print("  ⚠️  Сущность Wikidata не найдена")

    # ── Викисловарь ──
    print("\n📚 Шаг 4: Получение определения из Викисловаря...")
    wiktionary = fetch_wiktionary(api_wt, args.query)
    result["wiktionary"] = wiktionary
    if wiktionary:
        print(f"  ✅ Определение: {wiktionary.get('definition', '')[:80]}...")
    else:
        print("  ⚠️  Статья в Викисловаре не найдена")

    # ── Wikimedia Commons ──
    print("\n🖼  Шаг 5: Получение изображений из Wikimedia Commons...")
    commons_category = wikidata.get("commons_category") if wikidata else None
    commons = fetch_commons_images(api_cm, args.query, commons_category)
    result["commons"] = commons
    print(f"  ✅ Изображений: {len(commons.get('images', []))}")

    # ── Шаг 6: Picture of the Day ──
    if args.potd:
        print("\n🌅 Шаг 6: Получение Picture of the Day...")
        if args.potd_date:
            try:
                potd_date = datetime.strptime(args.potd_date, "%Y-%m-%d").date()
            except ValueError:
                print(
                    "  [!] Неверный формат даты, использую сегодня",
                    file=sys.stderr,
                )
                potd_date = date.today()
        else:
            potd_date = date.today()

        potd = fetch_picture_of_the_day(api_en, potd_date, Path(args.potd_dir))
        result["picture_of_the_day"] = potd
    else:
        print("\n🌅 Шаг 6: POTD пропущен (--no-potd)")

    # ── Cборка графа ──
    if args.graph:
        print(f"\n🕸  Шаг 7: Сбор статей для графа (мин. {args.min_articles})...")
        articles = collect_articles_for_graph(api_ru, title, args.min_articles)
        result["graph_articles_count"] = len(articles)
        result["graph_articles_titles"] = [a["title"] for a in articles]
        build_graph(title, articles, args.min_articles, output_name)
    else:
        print("\n🕸  Шаг 7: Построение графа пропущено (--no-graph)")

    # ── Сохранение JSON ──
    print(f"\n💾 Шаг 8: Сохранение результата в {output_json}...")
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"✅ JSON сохранён: {output_json}")

    # Итоговая сводка
    print("\n" + "=" * 60)
    print("📊 ИТОГОВАЯ СВОДКА:")
    print(f"  • Википедия: {wikipedia_data.get('title', '—')}")
    print(f"  • Wikidata: {wikidata.get('id', '—') if wikidata else '—'}")
    print(f"  • Викисловарь: {'есть' if wiktionary else 'нет'}")
    print(f"  • Commons: {len(commons.get('images', []))} файлов")
    if args.potd and result.get("picture_of_the_day"):
        print(f"  • POTD: {result['picture_of_the_day'].get('date', '—')}")
    if args.graph:
        print(f"  • Граф: {result.get('graph_articles_count', 0)} статей")
    print("=" * 60)

    return 0
# ============================================================
#endregion Main
# ============================================================

if __name__ == "__main__":
    sys.exit(main())