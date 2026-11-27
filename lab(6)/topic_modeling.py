#!/usr/bin/env python3
"""
Лабораторная работа №6: Векторный анализ веб-данных.
ИСПРАВЛЕННАЯ ВЕРСИЯ — coherence работает через gensim LDA.
"""

import argparse
import json
import re
import sys
import warnings
from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from tqdm import tqdm

warnings.filterwarnings("ignore", category=FutureWarning)

# ── NLP-зависимости ──
try:
    import pymorphy3
except ImportError:
    pymorphy3 = None

try:
    from nltk.corpus import stopwords
    RUSSIAN_STOPWORDS = set(stopwords.words("russian"))
except Exception:
    RUSSIAN_STOPWORDS = set()

# ── ML-зависимости ──
from sklearn.decomposition import NMF, PCA
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import (
    KMeans, AgglomerativeClustering, SpectralClustering,
)
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import normalize


# ============================================================
# 1. Предобработка текстов (без изменений)
# ============================================================
def tokenize(text: str) -> list[str]:
    if not isinstance(text, str):
        return []
    text = text.lower()
    text = re.sub(r"[^a-zа-яё\s]", " ", text)
    return text.split()


def lemmatize(tokens: list[str]) -> list[str]:
    if pymorphy3 is None:
        return tokens
    morph = pymorphy3.MorphAnalyzer()
    return [morph.parse(t)[0].normal_form if morph.parse(t) else t for t in tokens]


def remove_stopwords(tokens: list[str]) -> list[str]:
    return [t for t in tokens if t not in RUSSIAN_STOPWORDS and len(t) > 2]


def preprocess_text(text: str) -> str:
    tokens = tokenize(text)
    tokens = lemmatize(tokens)
    tokens = remove_stopwords(tokens)
    return " ".join(tokens)


def preprocess_corpus(texts: list[str]) -> tuple[list[str], list[list[str]]]:
    """Возвращает (очищенные строки, список токенов)."""
    cleaned = [preprocess_text(t) for t in tqdm(texts, desc="Предобработка")]
    tokens_list = [t.split() for t in cleaned if t.strip()]
    cleaned = [t for t in cleaned if t.strip()]
    return cleaned, tokens_list


# ============================================================
# 2. Загрузка датасетов (без изменений)
# ============================================================
def load_dataset(path: str, text_field: str = "text") -> list[str]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Файл не найден: {path}")
    if p.suffix == ".json":
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [item.get(text_field, "") or "" for item in data]
    elif p.suffix == ".csv":
        df = pd.read_csv(p)
        return df[text_field].fillna("").astype(str).tolist()
    else:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [item.get(text_field, "") or "" for item in data]


# ============================================================
# 3. Тематическое моделирование (ИСПРАВЛЕНО)
# ============================================================
def fit_lda_gensim(texts_tokens: list[list[str]], n_topics: int, n_features: int):
    """LDA через gensim — нативная поддержка CoherenceModel."""
    from gensim import corpora, models

    dictionary = corpora.Dictionary(texts_tokens)
    dictionary.filter_extremes(no_below=2, no_above=0.5, keep_n=n_features)
    corpus = [dictionary.doc2bow(text) for text in texts_tokens]

    model = models.LdaModel(
        corpus=corpus,
        id2word=dictionary,
        num_topics=n_topics,
        passes=15,
        iterations=100,
        random_state=42,
        alpha='auto',
        eta='auto',
    )
    return model, dictionary, corpus


def compute_coherence_gensim(model, dictionary, texts_tokens: list[list[str]]) -> float:
    """Coherence c_v для gensim LDA."""
    from gensim.models import CoherenceModel
    try:
        cm = CoherenceModel(
            model=model,
            texts=texts_tokens,
            dictionary=dictionary,
            coherence="c_v",
        )
        return cm.get_coherence()
    except Exception as e:
        print(f"  [!] Ошибка coherence: {e}", file=sys.stderr)
        return float("nan")


def fit_nmf_sklearn(texts: list[str], n_topics: int, n_features: int):
    """NMF через sklearn (TF-IDF)."""
    vectorizer = TfidfVectorizer(max_features=n_features)
    X_tfidf = vectorizer.fit_transform(texts)
    model = NMF(n_components=n_topics, max_iter=200, random_state=42)
    model.fit(X_tfidf)
    doc_topic = model.transform(X_tfidf)
    return model, vectorizer, doc_topic, X_tfidf


def get_top_words_gensim(model, dictionary, n_top_words: int):
    """Топ-слова для gensim LDA."""
    result = []
    for topic_id in range(model.num_topics):
        words = model.show_topic(topic_id, topn=n_top_words)
        result.append([(w, float(p)) for w, p in words])
    return result


def get_top_words_sklearn(model, feature_names: list[str], n_top_words: int):
    """Топ-слова для sklearn NMF."""
    result = []
    for topic in model.components_:
        top_idx = topic.argsort()[: -n_top_words - 1 : -1]
        result.append([(feature_names[i], float(topic[i])) for i in top_idx])
    return result


def find_optimal_k(texts_tokens: list[list[str]], k_range: range, n_features: int):
    """Подбор K через coherence (gensim LDA)."""
    scores = []
    for k in k_range:
        print(f"  → K={k}...", end=" ", flush=True)
        try:
            model, dictionary, corpus = fit_lda_gensim(texts_tokens, k, n_features)
            score = compute_coherence_gensim(model, dictionary, texts_tokens)
            scores.append((k, score))
            print(f"coherence={score:.4f}")
        except Exception as e:
            print(f"ошибка: {e}")
            scores.append((k, float("nan")))

    valid = [(k, s) for k, s in scores if not np.isnan(s)]
    if not valid:
        print("  ⚠️  Все coherence = NaN, использую K=5")
        return 5, scores
    best_k, best_score = max(valid, key=lambda x: x[1])
    return best_k, scores


# ============================================================
# 4. Визуализация (ИСПРАВЛЕНО — защита от пустого графика)
# ============================================================
def plot_top_words_gensim(model, dictionary, n_top_words: int, title: str, save_path: str):
    """Визуализация топ-слов для gensim LDA."""
    n_topics = model.num_topics
    cols = min(5, n_topics)
    rows = (n_topics + cols - 1) // cols

    fig, axes = plt.subplots(rows, cols, figsize=(5 * cols, 4 * rows), sharex=True)
    axes = axes.flatten() if n_topics > 1 else [axes]

    for topic_idx in range(n_topics):
        words = model.show_topic(topic_idx, topn=n_top_words)
        top_features = [w for w, p in words]
        weights = [p for w, p in words]

        ax = axes[topic_idx]
        ax.barh(top_features, weights, height=0.7,
                color=sns.color_palette("viridis", n_topics)[topic_idx % n_topics])
        ax.set_title(f"Топик {topic_idx + 1}", fontdict={"fontsize": 14})
        ax.invert_yaxis()
        ax.set_xlabel("Вероятность")

    for i in range(n_topics, len(axes)):
        axes[i].axis("off")

    plt.suptitle(title, fontsize=20, y=1.02)
    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  ✅ Визуализация сохранена: {save_path}")


def plot_top_words_sklearn(model, feature_names: list[str], n_top_words: int, title: str, save_path: str):
    """Визуализация топ-слов для sklearn NMF."""
    n_topics = model.components_.shape[0]
    cols = min(5, n_topics)
    rows = (n_topics + cols - 1) // cols

    fig, axes = plt.subplots(rows, cols, figsize=(5 * cols, 4 * rows), sharex=True)
    axes = axes.flatten() if n_topics > 1 else [axes]

    for topic_idx, topic in enumerate(model.components_):
        top_idx = topic.argsort()[: -n_top_words - 1 : -1]
        top_features = [feature_names[i] for i in top_idx]
        weights = topic[top_idx]

        ax = axes[topic_idx]
        ax.barh(top_features, weights, height=0.7,
                color=sns.color_palette("viridis", n_topics)[topic_idx % n_topics])
        ax.set_title(f"Топик {topic_idx + 1}", fontdict={"fontsize": 14})
        ax.invert_yaxis()
        ax.set_xlabel("Вес")

    for i in range(n_topics, len(axes)):
        axes[i].axis("off")

    plt.suptitle(title, fontsize=20, y=1.02)
    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  ✅ Визуализация сохранена: {save_path}")


def plot_coherence_curve(scores: list[tuple[int, float]], save_path: str):
    """График coherence от K — ИСПРАВЛЕНО: фильтрация NaN."""
    # Фильтруем NaN
    valid = [(k, s) for k, s in scores if not np.isnan(s)]
    
    if not valid:
        print(f"  ⚠️  Нет валидных coherence score — график не построен")
        # Создаём пустой график с пояснением
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.text(0.5, 0.5, "Нет данных: все coherence = NaN\nПроверьте установку gensim",
                ha='center', va='center', fontsize=14, color='red')
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis('off')
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
        plt.close()
        return

    ks, vals = zip(*valid)
    plt.figure(figsize=(10, 5))
    plt.plot(ks, vals, marker="o", linewidth=2, markersize=8)
    plt.xlabel("Число топиков (K)")
    plt.ylabel("Coherence score (c_v)")
    plt.title("Зависимость coherence от числа топиков")
    plt.grid(alpha=0.3)
    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  ✅ График coherence сохранён: {save_path}")


# ============================================================
# 5. Кластеризация городов (без изменений)
# ============================================================
def generate_demo_cities_matrix():
    cities = [
        "Пермь", "Кунгур", "Казань", "Уфа",
        "Москва", "СПб", "Петрозаводск", "Самара", "Екатеринбург", "Нижний Новгород",
    ]
    dishes = [
        "посикунчики", "пистики", "эчпочмак", "чак-чак", "беляши",
        "калитки", "карельская_рыба", "шанежки", "курьник", "строганина",
        "пельмени", "блины", "окрошка", "борщ", "солянка",
        "хачапури", "шаурма", "суши", "пицца", "паста",
    ]
    np.random.seed(42)
    X = np.random.rand(len(cities), len(dishes)) * 0.3
    X[0, 0:2] = [0.9, 0.85]
    X[1, 0:2] = [0.8, 0.9]
    X[2, 2:5] = [0.95, 0.9, 0.85]
    X[3, 2:5] = [0.85, 0.95, 0.8]
    X[6, 5:7] = [0.95, 0.9]
    X[4, 10:20] = np.random.rand(10) * 0.7 + 0.3
    X[5, 10:20] = np.random.rand(10) * 0.7 + 0.3
    return cities, dishes, X


def cluster_cities(X, cities, k, output_base):
    X_norm = normalize(X)
    methods = {
        "kmeans": KMeans(n_clusters=k, random_state=42, n_init=10),
        "hierarchical": AgglomerativeClustering(n_clusters=k, linkage="ward"),
        "spectral": SpectralClustering(n_clusters=k, affinity="cosine", random_state=42),
    }
    labels = {}
    for name, model in methods.items():
        labels[name] = model.fit_predict(X_norm)
        print(f"  ✅ {name}: кластеры = {np.bincount(labels[name])}")

    inertias = []
    K_range = range(2, min(10, len(cities)))
    for ki in K_range:
        km = KMeans(n_clusters=ki, random_state=42, n_init=10)
        km.fit(X_norm)
        inertias.append(km.inertia_)

    sil_scores = []
    for ki in K_range:
        if ki < len(cities):
            km = KMeans(n_clusters=ki, random_state=42, n_init=10)
            lbl = km.fit_predict(X_norm)
            sil_scores.append(silhouette_score(X_norm, lbl))
        else:
            sil_scores.append(float("nan"))

    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    pca = PCA(n_components=2)
    X_2d = pca.fit_transform(X_norm)
    ax = axes[0, 0]
    ax.scatter(X_2d[:, 0], X_2d[:, 1], c=labels["kmeans"], cmap="viridis", s=100, edgecolor="black")
    for i, city in enumerate(cities):
        ax.annotate(city, X_2d[i], fontsize=9, ha="center", va="bottom")
    ax.set_title(f"PCA-проекция (k-means, k={k})")
    ax.set_xlabel(f"PC1 ({pca.explained_variance_ratio_[0]:.1%})")
    ax.set_ylabel(f"PC2 ({pca.explained_variance_ratio_[1]:.1%})")
    ax.grid(alpha=0.3)

    ax = axes[0, 1]
    ax.plot(list(K_range), inertias, marker="o", linewidth=2)
    ax.set_title("Метод локтя")
    ax.set_xlabel("K")
    ax.set_ylabel("Inertia")
    ax.grid(alpha=0.3)

    ax = axes[1, 0]
    ax.plot(list(K_range), sil_scores, marker="o", linewidth=2, color="green")
    ax.set_title("Silhouette score")
    ax.set_xlabel("K")
    ax.set_ylabel("Score")
    ax.grid(alpha=0.3)

    ax = axes[1, 1]
    method_names = list(labels.keys())
    agreement = np.zeros((len(method_names), len(method_names)))
    for i, m1 in enumerate(method_names):
        for j, m2 in enumerate(method_names):
            same_m1 = labels[m1][:, None] == labels[m1][None, :]
            same_m2 = labels[m2][:, None] == labels[m2][None, :]
            agreement[i, j] = (same_m1 == same_m2).mean()
    sns.heatmap(agreement, annot=True, fmt=".2f",
                xticklabels=method_names, yticklabels=method_names,
                cmap="Blues", ax=ax, vmin=0.5, vmax=1.0)
    ax.set_title("Согласованность методов")

    plt.tight_layout()
    plt.savefig(f"{output_base}_clusters.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  ✅ Визуализация кластеров сохранена: {output_base}_clusters.png")

    df = pd.DataFrame({"city": cities})
    for name, lbl in labels.items():
        df[name] = lbl
    df.to_csv(f"{output_base}_clusters.csv", index=False, encoding="utf-8")
    print(f"  ✅ Результаты сохранены: {output_base}_clusters.csv")
    return labels


# ============================================================
# 6. CLI: тематическое моделирование (ИСПРАВЛЕНО)
# ============================================================
def cmd_topic(args):
    print(f"📚 Загрузка датасета: {args.dataset}")
    texts = load_dataset(args.dataset, args.text_field)
    print(f"  ✅ Документов: {len(texts)}")

    if len(texts) < args.min_docs:
        print(f"⚠️  Мало документов ({len(texts)}). Требуется минимум {args.min_docs}.", file=sys.stderr)
        return 1

    # Предобработка
    print("\n🧹 Предобработка корпуса...")
    texts_clean, texts_tokens = preprocess_corpus(texts)
    print(f"  ✅ После очистки: {len(texts_clean)} документов")

    # Подбор K или фиксированное значение
    if args.topics == "auto":
        print(f"\n🔍 Подбор оптимального K (gensim LDA)...")
        k_range = range(3, 21)
        best_k, scores = find_optimal_k(texts_tokens, k_range, args.n_features)
        print(f"  🏆 Оптимальное K = {best_k}")
        plot_coherence_curve(scores, f"{args.output}_coherence.png")
        n_topics = best_k
    else:
        n_topics = int(args.topics)

    # Обучение моделей
    methods_to_run = [args.method] if args.method != "both" else ["lda", "nmf"]

    for method in methods_to_run:
        print(f"\n🎯 Обучение {method.upper()} (K={n_topics})...")

        if method == "lda":
            # Gensim LDA
            model, dictionary, corpus = fit_lda_gensim(texts_tokens, n_topics, args.n_features)
            top_words = get_top_words_gensim(model, dictionary, args.n_top_words)
            
            # Coherence для финальной модели
            coherence = compute_coherence_gensim(model, dictionary, texts_tokens)
            print(f"  📊 Coherence (c_v) = {coherence:.4f}")

            # Печать топиков
            print(f"\n📊 Топики (LDA gensim):")
            for i, words in enumerate(top_words, 1):
                words_str = ", ".join(f"{w}({s:.3f})" for w, s in words)
                print(f"  Топик {i}: {words_str}")

            # Визуализация
            plot_top_words_gensim(
                model, dictionary, args.n_top_words,
                f"LDA (gensim) — топ-слова топиков",
                f"{args.output}_lda_topwords.png",
            )

            # Экспорт топиков в JSON
            topics_data = {
                "method": "lda_gensim",
                "n_topics": n_topics,
                "coherence": coherence,
                "topics": [
                    {"id": i + 1, "words": [{"word": w, "weight": s} for w, s in words]}
                    for i, words in enumerate(top_words)
                ],
            }
            with open(f"{args.output}_lda_topics.json", "w", encoding="utf-8") as f:
                json.dump(topics_data, f, ensure_ascii=False, indent=2)
            print(f"  ✅ Топики сохранены: {args.output}_lda_topics.json")

            # Матрица документ-топик
            doc_topic = np.array([model.get_document_topics(bow, minimum_probability=0) 
                                  for bow in corpus])
            # Преобразуем в массив (n_docs, n_topics)
            doc_topic_matrix = np.zeros((len(corpus), n_topics))
            for i, doc_topics in enumerate(doc_topic):
                for topic_id, prob in doc_topics:
                    doc_topic_matrix[i, topic_id] = prob

            df_doc_topic = pd.DataFrame(
                doc_topic_matrix,
                columns=[f"topic_{i+1}" for i in range(n_topics)],
            )
            df_doc_topic["dominant_topic"] = doc_topic_matrix.argmax(axis=1) + 1
            df_doc_topic["max_weight"] = doc_topic_matrix.max(axis=1)
            df_doc_topic.to_csv(f"{args.output}_lda_doc_topic.csv", index=False, encoding="utf-8")
            print(f"  ✅ Матрица документ-топик: {args.output}_lda_doc_topic.csv")

        else:  # nmf
            model, vec, doc_topic, X = fit_nmf_sklearn(texts_clean, n_topics, args.n_features)
            feature_names = vec.get_feature_names_out()
            top_words = get_top_words_sklearn(model, list(feature_names), args.n_top_words)

            print(f"\n📊 Топики (NMF sklearn):")
            for i, words in enumerate(top_words, 1):
                words_str = ", ".join(f"{w}({s:.3f})" for w, s in words)
                print(f"  Топик {i}: {words_str}")

            plot_top_words_sklearn(
                model, list(feature_names), args.n_top_words,
                f"NMF (sklearn) — топ-слова топиков",
                f"{args.output}_nmf_topwords.png",
            )

            topics_data = {
                "method": "nmf_sklearn",
                "n_topics": n_topics,
                "topics": [
                    {"id": i + 1, "words": [{"word": w, "weight": s} for w, s in words]}
                    for i, words in enumerate(top_words)
                ],
            }
            with open(f"{args.output}_nmf_topics.json", "w", encoding="utf-8") as f:
                json.dump(topics_data, f, ensure_ascii=False, indent=2)
            print(f"  ✅ Топики сохранены: {args.output}_nmf_topics.json")

            df_doc_topic = pd.DataFrame(
                doc_topic,
                columns=[f"topic_{i+1}" for i in range(n_topics)],
            )
            df_doc_topic["dominant_topic"] = doc_topic.argmax(axis=1) + 1
            df_doc_topic["max_weight"] = doc_topic.max(axis=1)
            df_doc_topic.to_csv(f"{args.output}_nmf_doc_topic.csv", index=False, encoding="utf-8")
            print(f"  ✅ Матрица документ-топик: {args.output}_nmf_doc_topic.csv")

    return 0


# ============================================================
# 7. CLI: кластеризация городов (без изменений)
# ============================================================
def cmd_cluster(args):
    print(f"🍲 Кластеризация городов (k={args.k})")
    if args.input:
        p = Path(args.input)
        if p.suffix == ".csv":
            df = pd.read_csv(p, index_col=0)
            cities = df.index.tolist()
            X = df.values
        else:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            cities = list(data.keys())
            all_dishes = sorted({d for c in data.values() for d in c.keys()})
            X = np.array([[data[c].get(d, 0.0) for d in all_dishes] for c in cities])
    else:
        print("  ℹ️  Используем демо-данные")
        cities, _, X = generate_demo_cities_matrix()

    print(f"  ✅ Городов: {len(cities)}, признаков: {X.shape[1]}")
    cluster_cities(X, cities, args.k, args.output)
    return 0


# ============================================================
# 8. Главный CLI
# ============================================================
def build_parser():
    parser = argparse.ArgumentParser(
        description="Векторный анализ веб-данных",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Примеры:\n"
            "  python topic_modeling.py topic --dataset demo_news.json --method lda --topics auto --output news_topics\n"
            "  python topic_modeling.py topic --dataset demo_news.json --method nmf --topics 5 --output news_nmf\n"
            "  python topic_modeling.py cluster --k 3 --output cities\n"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_topic = subparsers.add_parser("topic", help="Тематическое моделирование")
    p_topic.add_argument("--dataset", required=True, help="Путь к JSON/CSV")
    p_topic.add_argument("--text-field", default="text", help="Имя поля с текстом")
    p_topic.add_argument("--method", choices=["lda", "nmf", "both"], default="lda")
    p_topic.add_argument("--topics", default="auto", help="Число топиков или 'auto'")
    p_topic.add_argument("--n-features", type=int, default=1000)
    p_topic.add_argument("--n-top-words", type=int, default=10)
    p_topic.add_argument("--min-docs", type=int, default=50)
    p_topic.add_argument("--output", required=True)

    p_cluster = subparsers.add_parser("cluster", help="Кластеризация городов")
    p_cluster.add_argument("--input", help="Путь к CSV/JSON с матрицей")
    p_cluster.add_argument("--k", type=int, default=3)
    p_cluster.add_argument("--output", required=True)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "topic":
        return cmd_topic(args)
    elif args.command == "cluster":
        return cmd_cluster(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())