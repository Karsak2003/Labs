#!/usr/bin/env python3
"""Изоляция причины битого PDF: 5 вариантов одного и того же графа."""
import subprocess
from pathlib import Path
from urllib.parse import quote

T = "Менделеев, Дмитрий Иванович"
WIKI = "https://ru.wikipedia.org/wiki/"


def dot_source(url_mode: str, raw_newline: bool) -> str:
    label = ("Граф связей: " + T + ("\n" if raw_newline else "\\n") + "Статей: 2")
    if url_mode == "raw":
        url = WIKI + T                      # кириллица + пробелы + запятая
    elif url_mode == "encoded":
        url = WIKI + quote(T.replace(" ", "_"))
    else:
        url = None
    attr = f' URL="{url}"' if url else ""
    return (
        'digraph T {\n'
        '  graph [charset="UTF-8" rankdir="LR" fontname="DejaVu Sans"'
        f' label="{label}"]\n'
        '  node [shape=box style=filled fillcolor=lightyellow fontname="DejaVu Sans"]\n'
        f'  n0 [label="{T}"{attr}]\n'
        '  n1 [label="Химия"]\n'
        '  n0 -> n1\n'
        '}\n'
    )


def check(name: str, src: str):
    p = subprocess.run(["dot", "-Tpdf:cairo"], input=src.encode("utf-8"),
                       capture_output=True)
    d = p.stdout
    ok = d.startswith(b"%PDF-") and b"%%EOF" in d[-2048:]
    print(f"{name:<34} exit={p.returncode} байт={len(d):>7} ВАЛИДЕН={ok}")
    if not ok:
        err = [l for l in p.stderr.decode("utf-8", "replace").splitlines()
               if "[Graphviz]" not in l and l.strip()]
        for l in err[-6:]:
            print("      ", l)
    else:
        Path(f"iso_{name.split()[0]}.pdf").write_bytes(d)
    return ok


print("=== Через stdin->stdout (имена файлов не участвуют) ===")
check("V1_baseline", dot_source("none", False))
check("V2_URL_raw", dot_source("raw", False))
check("V3_URL_encoded", dot_source("encoded", False))
check("V4_raw_newline", dot_source("none", True))

print("\n=== V5: кириллическое имя файла (как в скрипте) ===")
src = dot_source("none", False)
Path("Менделеев.dot").write_text(src, encoding="utf-8")
p = subprocess.run(["dot", "-Tpdf:cairo", "Менделеев.dot", "-o", "Менделеев.pdf"],
                   capture_output=True)
f = Path("Менделеев.pdf")
d = f.read_bytes() if f.exists() else b""
ok = d.startswith(b"%PDF-") and b"%%EOF" in d[-2048:]
print(f"V5_cyrillic_filename exit={p.returncode} байт={len(d)} ВАЛИДЕН={ok}")
if not ok:
    print(p.stderr.decode("utf-8", "replace")[-800:])
    