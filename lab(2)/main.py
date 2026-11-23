#!/usr/bin/env python3
"""
Лабораторная работа №1: Граф информационно-аналитических веб-ресурсов
металлургической промышленности РФ и ближнего зарубежья.

Связи между ресурсами устанавливаются по пересечению ключевых терминов,
извлечённых из текстов страниц.
"""

import argparse
import sys
import time
# from pathlib import Path
from typing import NamedTuple

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

from razdel import sentenize, tokenize
import pymorphy3

try:
    import graphviz
except ImportError:
    graphviz = None


# ============================================================
# Константы и структуры данных
# ============================================================
AVAILABLE_PARSERS = ["html.parser", "lxml", "html5lib"]
AVAILABLE_FORMATS = ["pdf", "svg", "png"]

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Теги, из которых извлекаем основной текст (из лекции)
TEXT_TAGS = ["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "article", "section"]

STOP_WORDS = {
    "и", "в", "во", "не", "что", "он", "на", "я", "с", "со", "как",
    "а", "то", "все", "она", "так", "его", "но", "да", "ты", "к",
    "у", "же", "вы", "за", "бы", "по", "только", "ее", "мне", "было",
    "вот", "от", "меня", "еще", "нет", "о", "из", "ему", "теперь",
    "когда", "даже", "ну", "вдруг", "ли", "если", "уже", "или", "ни",
    "быть", "был", "была", "были", "это", "для", "чтобы", "есть",
    "каждый", "который", "его", "её", "их", "мы", "вы", "они",
    "этот", "тот", "такой", "какой", "можно", "нужно", "иметь",
    "год", "года", "лет", "г", "т", "д", "руб", "тыс", "млн",
    "также", "однако", "кроме", "через", "между", "после", "перед",
    "при", "над", "под", "о", "об", "без", "до", "от", "к", "по",
}

EXCLUDED_POS = {
    "PREP",  # предлог
    "CONJ",  # союз
    "PRCL",  # частица
    "INTJ",  # междометие
    "NPRO",  # местоимение
    "NUMR",  # числительное
    "Apro",  # местоимение-прилагательное
}


# Ленивая инициализация — создаётся один раз
_morph_analyzer = None

def _get_morph():
    global _morph_analyzer
    if _morph_analyzer is None:
        _morph_analyzer = pymorphy3.MorphAnalyzer()
    return _morph_analyzer


class Resource(NamedTuple):
    """Один ресурс графа: URL + набор терминов."""
    url: str
    name: str          # короткое имя узла (домен)
    terms: set[str]    # ключевые термины
    text_len: int      # длина извлечённого текста


# ============================================================
# 1. CLI-парсер (argparse)
# ============================================================
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Построение графа металлургических веб-ресурсов",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Примеры:\n"
            "  python metallurgy_graph.py urls.txt\n"
            "  python metallurgy_graph.py urls.txt --parser lxml --threshold 3\n"
            "  python metallurgy_graph.py urls.txt --no-render\n"
            "  python metallurgy_graph.py urls.txt --render --format svg\n"
        ),
    )
    parser.add_argument(
        "input_file",
        help="Путь к текстовому файлу со списком URL (по одному на строку)",
    )
    parser.add_argument(
        "--parser",
        choices=AVAILABLE_PARSERS,
        default="lxml",
        help=(
            "Парсер BeautifulSoup. "
            "html.parser — встроен, средняя скорость; "
            "lxml — быстрый C-парсер (рекомендуется); "
            "html5lib — самый точный, имитирует браузер (медленный)"
        ),
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=3,
        help="Минимальное число общих терминов для создания ребра (по умолчанию 3)",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=50,
        help="Сколько топ-терминов брать с каждой страницы (по умолчанию 50)",
    )
    parser.add_argument(
        "--render/--no-render",
        dest="render",
        default=True,
        help="Рендерить граф в файл (по умолчанию ДА). DOT сохраняется всегда",
    )
    parser.add_argument(
        "--format",
        choices=AVAILABLE_FORMATS,
        default="pdf",
        help="Формат рендеринга графа (по умолчанию pdf)",
    )
    parser.add_argument(
        "--output",
        default="metallurgy_graph",
        help="Базовое имя выходного файла (без расширения)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=15,
        help="Таймаут HTTP-запроса в секундах (по умолчанию 15)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Задержка между запросами в секундах (этикет краулера)",
    )
    return parser


# ============================================================
# 2. Загрузка и парсинг страницы (Паттерн 1 из лекции)
# ============================================================
def fetch_page(url: str, parser: str, timeout: int) -> BeautifulSoup | None:
    """
    Паттерн 1 из лекции: requests + BS4.
    Возвращает BeautifulSoup-объект или None при ошибке.
    """
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()  # бросает исключение на 4xx/5xx

        # Явно указываем парсер — требование лекции
        return BeautifulSoup(resp.text, parser)
    except requests.RequestException as e:
        print(f"  [!] Ошибка загрузки {url}: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  [!] Ошибка парсинга {url}: {e}", file=sys.stderr)
        return None


# ============================================================
# 3. Извлечение текста и терминов
# ============================================================
def extract_text(soup: BeautifulSoup) -> str:
    """
    Извлекает основной текст из HTML.
    Убираем скрипты, стили, навигацию — оставляем смысловой контент.
    """
    # Удаляем ненужные блоки
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()

    # Собираем текст из смысловых тегов
    pieces = []
    for tag in soup.find_all(TEXT_TAGS):
        text = tag.get_text(separator=" ", strip=True)
        if text:
            pieces.append(text)

    return " ".join(pieces)


def extract_terms(text: str, top_n: int) -> set[str]:
    """
    Извлекает ключевые термины через pymorphy3 + razdel.
    Термины — это substantive-словосочетания (прил+сущ) и одиночные сущ.
    в нормальной форме (именительный падеж, ед.ч.).
    """
    if not text or len(text) < 50:
        return set()

    morph = _get_morph()
    term_freq: dict[str, int] = {}

    # Разбиваем на предложения, затем на токены
    for sent in sentenize(text):
        tokens = list(tokenize(sent.text))
        # Получаем разборы для всех токенов
        parses = []
        for t in tokens:
            if t.text.strip().lower() in STOP_WORDS:
                parses.append(None)
                continue
            p = morph.parse(t.text)
            if not p:
                parses.append(None)
                continue
            # Берём наиболее вероятный разбор
            best = p[0]
            if best.tag.POS in EXCLUDED_POS:
                parses.append(None)
                continue
            parses.append(best)

        # Ищем биграммы: прилагательное + существительное
        for i in range(len(parses) - 1):
            cur = parses[i]
            nxt = parses[i + 1]
            if cur is None or nxt is None:
                continue

            if cur.tag.POS == "ADJF" and nxt.tag.POS == "NOUN":
                # Составной термин
                term = f"{cur.normal_form} {nxt.normal_form}"
                term_freq[term] = term_freq.get(term, 0) + 1
            elif cur.tag.POS == "NOUN" and nxt.tag.POS == "NOUN":
                # Редкие, но возможные составные термины (падеж-падеж)
                term = f"{cur.normal_form} {nxt.normal_form}"
                term_freq[term] = term_freq.get(term, 0) + 1

        # Одиночные существительные
        for p in parses:
            if p is not None and p.tag.POS == "NOUN":
                lemma = p.normal_form
                # Фильтруем слишком короткие и не-кириллицу
                if len(lemma) >= 4 and lemma.isalpha():
                    term_freq[lemma] = term_freq.get(lemma, 0) + 1

    # Сортируем по частоте, берём top_n
    sorted_terms = sorted(term_freq.items(), key=lambda x: -x[1])
    return {t for t, _ in sorted_terms[:top_n]}

def extract_domain(url: str) -> str:
    """Короткое имя узла — домен без протокола и www."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    host = parsed.netloc or parsed.path
    host = host.replace("www.", "")
    return host


# ============================================================
# 4. Построение графа
# ============================================================
def build_graph(
    resources: list[Resource],
    threshold: int,
) -> "graphviz.Digraph":
    """
    Строит граф: узлы — ресурсы, рёбра — пересечение терминов >= threshold.
    """
    if graphviz is None:
        raise RuntimeError(
            "graphviz не установлен. Выполните: pip install graphviz"
        )

    dot = graphviz.Digraph(
        name="MetallurgyGraph",
        comment="Граф металлургических веб-ресурсов",
        format="pdf",  # переопределим при рендере
    )
    dot.attr(
        rankdir="LR",
        label="Граф металлургических веб-ресурсов\\nСвязи по общим ключевым терминам",
        labelloc="t",
        fontsize="16",
    )
    dot.attr("node", shape="box", style="filled", fillcolor="lightblue")
    dot.attr("edge", color="gray60")

    # Добавляем узлы
    for r in resources:
        tooltip = f"{r.url}\\nТерминов: {len(r.terms)}"
        dot.node(
            r.name,
            label=r.name,
            URL=r.url,
            tooltip=tooltip,
        )

    # Добавляем рёбра по пересечению терминов
    edges_count = 0
    for i in range(len(resources)):
        for j in range(i + 1, len(resources)):
            common = resources[i].terms & resources[j].terms
            if len(common) >= threshold:
                # Толщина ребра пропорциональна числу общих терминов
                penwidth = min(1.0 + len(common) * 0.3, 5.0)
                dot.edge(
                    resources[i].name,
                    resources[j].name,
                    penwidth=str(penwidth),
                    label=str(len(common)),
                    tooltip=", ".join(sorted(list(common))[:10]),
                )
                edges_count += 1

    print(f"✅ Граф построен: {len(resources)} узлов, {edges_count} рёбер")
    return dot


# ============================================================
# 5. Сохранение DOT и рендеринг
# ============================================================
def save_graph(
    dot,
    output_base: str,
    render: bool,
    fmt: str,
) -> None:
    """
    DOT-файл сохраняется ВСЕГДА.
    Рендеринг (pdf/svg/png) — опционально.
    """
    # 1. DOT-файл — всегда (через with open)
    dot_path = f"{output_base}.dot"
    with open(dot_path, "w", encoding="utf-8") as file:
        file.write(dot.source)
    print(f"💾 DOT-файл сохранён: {dot_path}")

    # 2. Рендеринг — если запрошен
    if render:
        dot.format = fmt
        rendered_path = dot.render(filename=output_base, cleanup=True)
        print(f"🖼️ Граф отрендерен в: {rendered_path}")
    else:
        print("ℹ️  Рендеринг пропущен (--no-render)")


# ============================================================
# 6. Основная логика
# ============================================================
def load_urls(path: str) -> list[str]:
    """Читает URL-ы из файла, игнорирует пустые строки и комментарии."""
    urls = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if not line.startswith(("http://", "https://")):
                line = "https://" + line
            urls.append(line)
    return urls


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if graphviz is None:
        print("❌ graphviz не установлен", file=sys.stderr)
        return 1

    # Проверка системного graphviz при рендере
    if args.render:
        import shutil
        if shutil.which("dot") is None:
            print(
                "❌ Системный graphviz (бинарь 'dot') не найден. "
                "Установите: apt install graphviz / choco install graphviz / brew install graphviz",
                file=sys.stderr,
            )
            return 1

    # Загрузка URL
    urls = load_urls(args.input_file)
    if len(urls) < 25:
        print(
            f"⚠️  В списке только {len(urls)} URL. По заданию требуется минимум 25.",
            file=sys.stderr,
        )

    print(f"🌐 Парсер BS4: {args.parser}")
    print(f"🔗 URL-ов в списке: {len(urls)}")
    print(f"🎯 Порог пересечения терминов: {args.threshold}")
    print(f"📊 Топ-N терминов с каждой страницы: {args.top_n}")
    print(f"🖼️  Рендеринг: {'ДА (' + args.format + ')' if args.render else 'НЕТ'}")
    print("─" * 60)

    # Сбор ресурсов
    resources: list[Resource] = []
    failed = 0

    for url in tqdm(urls, desc="Сбор ресурсов"):
        soup = fetch_page(url, args.parser, args.timeout)
        if soup is None:
            failed += 1
            continue

        text = extract_text(soup)
        terms = extract_terms(text, args.top_n)

        if not terms:
            print(f"  [!] Нет терминов на {url}", file=sys.stderr)
            continue

        resources.append(Resource(
            url=url,
            name=extract_domain(url),
            terms=terms,
            text_len=len(text),
        ))

        # Этикет краулера
        time.sleep(args.delay)

    print("─" * 60)
    print(f"✅ Успешно обработано: {len(resources)}")
    print(f"❌ Ошибок: {failed}")

    if len(resources) < 2:
        print("❌ Недостаточно ресурсов для построения графа", file=sys.stderr)
        return 1

    # Построение графа
    dot = build_graph(resources, args.threshold)

    # Сохранение
    save_graph(dot, args.output, args.render, args.format)

    # Итоговая статистика
    print("\n📈 Статистика по ресурсам:")
    for r in sorted(resources, key=lambda x: len(x.terms), reverse=True)[:5]:
        print(f"  • {r.name:<30} терминов: {len(r.terms):<4} текста: {r.text_len}")

    return 0


if __name__ == "__main__":
    sys.exit(main())