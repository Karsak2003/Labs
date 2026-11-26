#!/usr/bin/env python3
"""Диагностика graphviz: что реально доступно и валиден ли PDF."""
import shutil, subprocess, sys
from pathlib import Path

print("dot:", shutil.which("dot"))
if not shutil.which("dot"):
    sys.exit("dot не найден в PATH")

print(subprocess.run(["dot", "-V"], capture_output=True, text=True).stderr.strip())

# Какие рендереры доступны для pdf? (должен быть cairo)
r = subprocess.run(["dot", "-Tpdf:"], capture_output=True, text=True)
print("Рендереры pdf:", (r.stderr or r.stdout).strip())

TEST = '''digraph T {
  graph [charset="UTF-8" fontname="DejaVu Sans" label="Тест\\nКириллица"]
  node [shape=box fontname="DejaVu Sans"]
  n0 [label="Менделеев, Дмитрий Иванович"]
  n1 [label="Химия"]
  n0 -> n1
}'''

for fmt in ("pdf", "svg", "png"):
    p = subprocess.run(["dot", f"-T{fmt}", "-v"],
                       input=TEST.encode("utf-8"), capture_output=True)
    data = p.stdout
    print(f"\n--- {fmt}: exit={p.returncode}, байт={len(data)}")
    print("stderr:", p.stderr.decode("utf-8", "replace").strip()[-600:])
    if fmt == "pdf":
        print("заголовок:", data[:8], "| хвост:", data[-8:])
        ok = data.startswith(b"%PDF-") and b"%%EOF" in data[-1024:]
        print("ВАЛИДНЫЙ PDF:", ok)
        if ok:
            Path("test_graphviz.pdf").write_bytes(data)
            print("→ открой test_graphviz.pdf")