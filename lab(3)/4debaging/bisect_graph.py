#!/usr/bin/env python3
"""Бисекция: что именно ломает PDF в реальном DOT-файле."""
import re, subprocess, sys
from pathlib import Path

ID = r'"(?:[^"\\]|\\.)*"'


def fix_newlines(src: str) -> str:
    """Реальный 0x0A внутри кавычек -> DOT-escape \\n."""
    out, in_q, esc = [], False, False
    for ch in src:
        if in_q:
            if esc:
                out.append(ch); esc = False; continue
            if ch == "\\":
                out.append(ch); esc = True; continue
            if ch == '"':
                in_q = False; out.append(ch); continue
            if ch == "\n":
                out.append("\\n"); continue
            if ch == "\r":
                continue
            out.append(ch)
        else:
            if ch == '"':
                in_q = True
            out.append(ch)
    return "".join(out)


def strip_urls(src: str) -> str:
    return re.sub(r'\s*URL=' + ID, '', src)


def ascii_ids(src: str) -> str:
    ids = {}
    def get(tok):
        return ids.setdefault(tok, f'"n{len(ids)}"')
    lines = []
    for line in src.splitlines():
        m = re.match(r'^(\s*)(' + ID + r')(\s*\[)', line)
        if m:
            line = m.group(1) + get(m.group(2)) + line[m.end(2):]
        m = re.match(r'^(\s*)(' + ID + r')(\s*->\s*)(' + ID + r')(.*)$', line)
        if m:
            line = m.group(1) + get(m.group(2)) + m.group(3) + get(m.group(4)) + m.group(5)
        lines.append(line)
    return "\n".join(lines) + "\n"


path = Path(sys.argv[1]) if len(sys.argv) > 1 else max(
    Path(".").glob("*.dot"), key=lambda p: p.stat().st_mtime, default=None)
if not path:
    sys.exit("Не найден .dot файл — передай путь аргументом")
print("Файл:", path)

src = path.read_text(encoding="utf-8")
v1 = fix_newlines(src)
v2 = strip_urls(v1)
v3 = ascii_ids(v2)

for name, text in (("V0_asis", src), ("V1_newline", v1),
                   ("V2_noURL", v2), ("V3_asciiIDs", v3)):
    p = subprocess.run(["dot", "-Tpdf"], input=text.encode("utf-8"),
                       capture_output=True)
    d = p.stdout
    ok = d.startswith(b"%PDF-") and b"%%EOF" in d[-2048:]
    print(f"{name:12} exit={p.returncode} байт={len(d):7} ВАЛИДЕН={ok}")
    if not ok and p.stderr:
        print("   stderr:", p.stderr.decode("utf-8", "replace").strip()[-300:])
    if ok:
        Path(f"bisect_{name}.pdf").write_bytes(d)
        