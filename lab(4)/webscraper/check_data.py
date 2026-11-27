import sys
import pandas as pd


def main(path: str) -> int:
    df = pd.read_json(path) if path.endswith(".json") else pd.read_csv(path)
    print(f"Файл: {path}\nЗаписей: {len(df)}  Колонок: {len(df.columns)}\n")

    print("── Пропуски ──")
    na = df.isna().sum()
    print(na[na > 0].to_string() if na.any() else "нет")

    print("\n── Дубликаты ──")
    if "url" in df:
        print(f"по url:   {df.duplicated(subset=['url']).sum()}")
    if "title" in df:
        print(f"по title: {df.duplicated(subset=['title']).sum()}")

    print("\n── Выбросы (IQR) ──")
    for col in ("price", "rating", "reviews_count"):
        if col not in df:
            continue
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        if s.empty:
            continue
        q1, q3 = s.quantile(0.25), s.quantile(0.75)
        iqr = q3 - q1
        lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        out = s[(s < lo) | (s > hi)]
        print(f"{col}: n={len(s)}, min={s.min()}, median={s.median()}, "
              f"max={s.max()}, выбросов={len(out)}")

    print("\n── Требование ЛР ──")
    print("✅ ≥ 100 записей" if len(df) >= 100 else f"❌ только {len(df)} < 100")
    return 0 if len(df) >= 100 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))