#!/usr/bin/env python3
"""
Лабораторная работа №7: Система автоматического анализа видеоданных.

Подкоманды:
  download  — скачать видео и метаданные
  analyze   — проанализировать видео (кадры + аудио)
  cluster   — сгруппировать видео по темам
  search    — поиск по событиям
  timeline  — показать временную шкалу событий

Архитектура пайплайна:
  Сбор → Декомпозиция → Визуальный анализ → Аудио анализ →
  → Временные события → Группировка → Интерфейс
"""

import argparse
import json
import subprocess
import sys
import warnings
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from tqdm import tqdm

warnings.filterwarnings("ignore", category=FutureWarning)


# ============================================================
# 1. Утилиты: метаданные и декодирование
# ============================================================
def get_video_metadata_ffprobe(video_path: str) -> dict:
    """
    Извлекает технические метаданные через ffprobe.
    Возвращает: кодек, разрешение, fps, битрейт, длительность.
    """
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams", "-show_format",
        str(video_path),
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
        data = json.loads(out)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"  [!] ffprobe не доступен: {e}", file=sys.stderr)
        return {}

    video_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
        {},
    )
    audio_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "audio"),
        {},
    )
    fmt = data.get("format", {})

    # Парсим fps (может быть дробью "30000/1001")
    fps_str = video_stream.get("avg_frame_rate", "0/1")
    try:
        if "/" in fps_str:
            num, den = fps_str.split("/")
            fps = float(num) / float(den) if float(den) != 0 else 0
        else:
            fps = float(fps_str)
    except (ValueError, ZeroDivisionError):
        fps = 0.0

    return {
        "codec": video_stream.get("codec_name"),
        "width": video_stream.get("width"),
        "height": video_stream.get("height"),
        "fps": round(fps, 2),
        "duration": float(fmt.get("duration", 0)),
        "bit_rate": int(fmt.get("bit_rate", 0)) if fmt.get("bit_rate") else None,
        "has_audio": bool(audio_stream),
        "size_mb": round(int(fmt.get("size", 0)) / 1024 / 1024, 2),
    }


def extract_audio(video_path: str, audio_path: str) -> bool:
    """
    Извлекает аудио из видео в формат для Whisper (mono, 16kHz).
    """
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-ac", "1", "-ar", "16000",
        str(audio_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"  [!] Ошибка извлечения аудио: {e}", file=sys.stderr)
        return False


# ============================================================
# 2. Сбор видео и метаданных (yt-dlp)
# ============================================================
def download_video(url: str, output_dir: Path) -> dict:
    """
    Скачивает видео и метаданные через yt-dlp.
    Возвращает словарь с путями и метаданными.
    """
    try:
        import yt_dlp
    except ImportError:
        print("  [!] yt-dlp не установлен: pip install yt-dlp", file=sys.stderr)
        return {}

    output_dir.mkdir(parents=True, exist_ok=True)
    outtmpl = str(output_dir / "%(id)s.%(ext)s")

    ydl_opts = {
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "writesubtitles": False,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            video_id = info.get("id", "unknown")
            filename = ydl.prepare_filename(info)

            metadata = {
                "id": video_id,
                "url": url,
                "title": info.get("title", ""),
                "description": info.get("description", ""),
                "duration": info.get("duration"),
                "upload_date": info.get("upload_date"),
                "view_count": info.get("view_count"),
                "like_count": info.get("like_count"),
                "comment_count": info.get("comment_count"),
                "categories": info.get("categories", []),
                "tags": info.get("tags", []),
                "local_file": filename,
            }

            # Сохраняем метаданные в JSON
            meta_path = output_dir / f"{video_id}_meta.json"
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)

            print(f"  ✅ Скачано: {filename}")
            print(f"  ✅ Метаданные: {meta_path}")
            return metadata

    except Exception as e:
        print(f"  [!] Ошибка скачивания {url}: {e}", file=sys.stderr)
        return {}


# ============================================================
# 3. Визуальный анализ: YOLO детекция объектов
# ============================================================
def detect_objects_in_frames(
    video_path: str,
    fps_sample: float = 1.0,
    conf_threshold: float = 0.4,
    model_name: str = "yolov8n.pt",
) -> list[dict]:
    """
    Детектирует объекты в кадрах с заданным шагом (по умолчанию 1 кадр/сек).
    Возвращает список событий: {time, objects: [{class, conf, bbox}]}.
    """
    try:
        import cv2
        from ultralytics import YOLO
    except ImportError as e:
        print(f"  [!] Не установлены зависимости: {e}", file=sys.stderr)
        return []

    model = YOLO(model_name)
    cap = cv2.VideoCapture(str(video_path))

    if not cap.isOpened():
        print(f"  [!] Не удалось открыть видео: {video_path}", file=sys.stderr)
        return []

    video_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frame_step = max(1, int(round(video_fps / fps_sample)))

    events = []
    frame_idx = 0
    processed = 0

    with tqdm(total=total_frames // frame_step, desc="Детекция объектов") as pbar:
        while True:
            ok, frame = cap.read()
            if not ok:
                break

            if frame_idx % frame_step == 0:
                timestamp = frame_idx / video_fps
                # YOLO работает с BGR из OpenCV
                results = model.predict(frame, conf=conf_threshold, verbose=False)

                objects = []
                if results and len(results) > 0:
                    for box in results[0].boxes:
                        cls_id = int(box.cls[0])
                        cls_name = model.names[cls_id]
                        conf = float(box.conf[0])
                        bbox = box.xyxy[0].tolist()
                        objects.append({
                            "class": cls_name,
                            "conf": round(conf, 3),
                            "bbox": [round(v, 1) for v in bbox],
                        })

                events.append({
                    "time": round(timestamp, 2),
                    "frame_idx": frame_idx,
                    "objects": objects,
                })
                processed += 1
                pbar.update(1)

            frame_idx += 1

    cap.release()
    print(f"  ✅ Обработано кадров: {processed}, событий: {len(events)}")
    return events


# ============================================================
# 4. Аудио анализ: Whisper транскрипция
# ============================================================
def transcribe_audio(
    audio_path: str,
    model_name: str = "base",
    language: str = "ru",
) -> list[dict]:
    """
    Транскрибирует аудио через Whisper.
    Возвращает список сегментов: {start, end, text}.
    """
    try:
        import whisper
    except ImportError:
        print("  [!] whisper не установлен: pip install openai-whisper", file=sys.stderr)
        return []

    if not Path(audio_path).exists():
        print(f"  [!] Аудиофайл не найден: {audio_path}", file=sys.stderr)
        return []

    print(f"  ⏳ Загрузка модели Whisper '{model_name}'...")
    model = whisper.load_model(model_name)

    print(f"  ⏳ Транскрипция (язык={language})...")
    result = model.transcribe(
        audio_path,
        language=language,
        verbose=False,
    )

    segments = []
    for seg in result.get("segments", []):
        segments.append({
            "start": round(seg["start"], 2),
            "end": round(seg["end"], 2),
            "text": seg["text"].strip(),
        })

    if not segments:
        print("  ⚠️  Транскрипт пустой — проверьте, есть ли речь в аудио", file=sys.stderr)
    else:
        print(f"  ✅ Сегментов распознано: {len(segments)}")

    return segments


# ============================================================
# 5. Выявление событий на временной шкале
# ============================================================
def build_timeline(
    visual_events: list[dict],
    audio_segments: list[dict],
    keywords: Optional[list[str]] = None,
) -> list[dict]:
    """
    Объединяет визуальные и аудио события в единую шкалу.
    Каждое событие: {time, type, description, confidence}.
    """
    timeline = []

    # Визуальные события — моменты, когда появляются значимые объекты
    for ev in visual_events:
        if ev["objects"]:
            # Группируем объекты по времени
            obj_names = [o["class"] for o in ev["objects"]]
            avg_conf = np.mean([o["conf"] for o in ev["objects"]])
            timeline.append({
                "time": ev["time"],
                "type": "visual",
                "description": f"Обнаружены: {', '.join(set(obj_names))}",
                "objects": obj_names,
                "confidence": round(float(avg_conf), 3),
            })

    # Аудио события — ключевые слова в транскрипте
    if keywords:
        keywords_lower = [k.lower() for k in keywords]
        for seg in audio_segments:
            text_lower = seg["text"].lower()
            matched = [k for k in keywords_lower if k in text_lower]
            if matched:
                timeline.append({
                    "time": seg["start"],
                    "type": "audio",
                    "description": f"Ключевые слова: {', '.join(matched)} — \"{seg['text']}\"",
                    "matched_keywords": matched,
                    "text": seg["text"],
                    "confidence": 1.0,
                })

    # Сортируем по времени
    timeline.sort(key=lambda x: x["time"])
    return timeline


# ============================================================
# 6. Группировка видео по темам
# ============================================================
def cluster_videos(videos_data: list[dict], n_clusters: int = 5) -> list[dict]:
    """
    Группирует видео по темам через TF-IDF + KMeans.
    Источники текста: название + описание + транскрипт.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.cluster import KMeans

    docs = []
    for v in videos_data:
        parts = [
            v.get("title", ""),
            v.get("description", ""),
            " ".join(s.get("text", "") for s in v.get("transcript", [])),
        ]
        docs.append(" ".join(parts))

    if not docs or all(not d.strip() for d in docs):
        print("  ⚠️  Нет текстов для кластеризации", file=sys.stderr)
        return videos_data

    print(f"  ⏳ Построение TF-IDF матрицы ({len(docs)} документов)...")
    vectorizer = TfidfVectorizer(max_features=5000)
    X = vectorizer.fit_transform(docs)

    # Подбор K (если видео меньше, чем кластеров)
    k = min(n_clusters, len(docs))
    if k < 2:
        print("  ⚠️  Недостаточно видео для кластеризации", file=sys.stderr)
        return videos_data

    print(f"  ⏳ Кластеризация (K={k})...")
    kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
    labels = kmeans.fit_predict(X)

    # Топ-слова для каждого кластера
    feature_names = vectorizer.get_feature_names_out()
    cluster_topics = {}
    for i in range(k):
        center = kmeans.cluster_centers_[i]
        top_idx = center.argsort()[-10:][::-1]
        top_words = [feature_names[j] for j in top_idx]
        cluster_topics[i] = top_words

    # Присваиваем метки видео
    for v, lab in zip(videos_data, labels):
        v["cluster"] = int(lab)
        v["cluster_topic_words"] = cluster_topics[int(lab)]

    # Печатаем результаты
    print("\n📊 Тематические кластеры:")
    for i in range(k):
        cluster_videos_list = [v for v in videos_data if v.get("cluster") == i]
        words = ", ".join(cluster_topics[i][:5])
        print(f"  Кластер {i} ({len(cluster_videos_list)} видео): {words}")

    return videos_data


# ============================================================
# 7. Поиск по событиям
# ============================================================
def search_events(videos_data: list[dict], query: str) -> list[dict]:
    """
    Ищет события по запросу в транскрипте и описаниях объектов.
    """
    query_lower = query.lower()
    hits = []

    for v in videos_data:
        video_id = v.get("id", "unknown")
        title = v.get("title", "")

        # Поиск в транскрипте
        for seg in v.get("transcript", []):
            if query_lower in seg.get("text", "").lower():
                hits.append({
                    "video_id": video_id,
                    "title": title,
                    "time": seg["start"],
                    "type": "transcript",
                    "text": seg["text"],
                })

        # Поиск в визуальных событиях
        for ev in v.get("visual_events", []):
            obj_names = [o["class"].lower() for o in ev.get("objects", [])]
            if any(query_lower in name for name in obj_names):
                hits.append({
                    "video_id": video_id,
                    "title": title,
                    "time": ev["time"],
                    "type": "visual",
                    "text": f"Объекты: {', '.join(obj_names)}",
                })

    hits.sort(key=lambda x: (x["video_id"], x["time"]))
    return hits


# ============================================================
# 8. CLI-подкоманды
# ============================================================
def cmd_download(args):
    """Скачивает видео и извлекает метаданные."""
    print(f"📥 Скачивание: {args.url}")
    output_dir = Path(args.output_dir)

    metadata = download_video(args.url, output_dir)
    if not metadata:
        return 1

    # Технические метаданные через ffprobe
    video_path = metadata.get("local_file")
    if video_path and Path(video_path).exists():
        tech_meta = get_video_metadata_ffprobe(video_path)
        metadata["technical"] = tech_meta
        print(f"  ✅ Тех. метаданные: {tech_meta.get('codec')} "
              f"{tech_meta.get('width')}x{tech_meta.get('height')} "
              f"@ {tech_meta.get('fps')} fps, {tech_meta.get('duration')}s")

        # Сохраняем обновлённые метаданные
        meta_path = output_dir / f"{metadata['id']}_meta.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

    return 0


def cmd_analyze(args):
    """Анализирует видео: детекция объектов + транскрипция."""
    video_path = Path(args.video)
    if not video_path.exists():
        print(f"❌ Видео не найдено: {video_path}", file=sys.stderr)
        return 1

    print(f"🎬 Анализ видео: {video_path}")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    video_id = video_path.stem
    result = {
        "id": video_id,
        "file": str(video_path),
    }

    # 1. Технические метаданные
    print("\n📊 Шаг 1: Технические метаданные...")
    tech_meta = get_video_metadata_ffprobe(str(video_path))
    result["technical"] = tech_meta
    for k, v in tech_meta.items():
        print(f"  • {k}: {v}")

    if not tech_meta.get("duration"):
        print("  ⚠️  Не удалось определить длительность", file=sys.stderr)

    # 2. Извлечение аудио
    audio_path = output_dir / f"{video_id}_audio.wav"
    if tech_meta.get("has_audio", True):
        print(f"\n🎵 Шаг 2: Извлечение аудио → {audio_path}")
        if extract_audio(str(video_path), str(audio_path)):
            print(f"  ✅ Аудио сохранено")
        else:
            print(f"  ⚠️  Не удалось извлечь аудио")
            audio_path = None
    else:
        print("\n🎵 Шаг 2: Аудио отсутствует — пропуск транскрипции")
        audio_path = None

    # 3. Визуальный анализ
    print(f"\n👁  Шаг 3: Детекция объектов (YOLO, conf={args.conf})...")
    visual_events = detect_objects_in_frames(
        str(video_path),
        fps_sample=args.fps_sample,
        conf_threshold=args.conf,
        model_name=args.yolo_model,
    )
    result["visual_events"] = visual_events

    # Статистика по объектам
    all_objects = [o["class"] for ev in visual_events for o in ev["objects"]]
    if all_objects:
        from collections import Counter
        obj_counts = Counter(all_objects)
        print(f"  📈 Топ-объекты: {obj_counts.most_common(5)}")

    # 4. Транскрипция
    if audio_path and audio_path.exists():
        print(f"\n🗣  Шаг 4: Транскрипция (Whisper, model={args.whisper_model})...")
        transcript = transcribe_audio(
            str(audio_path),
            model_name=args.whisper_model,
            language=args.language,
        )
        result["transcript"] = transcript
    else:
        result["transcript"] = []

    # 5. Построение временной шкалы
    print("\n⏱  Шаг 5: Построение временной шкалы событий...")
    timeline = build_timeline(
        visual_events,
        result["transcript"],
        keywords=args.keywords.split(",") if args.keywords else None,
    )
    result["timeline"] = timeline
    print(f"  ✅ Всего событий на шкале: {len(timeline)}")

    # 6. Сохранение результата
    out_path = output_dir / f"{video_id}_analysis.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n💾 Результат сохранён: {out_path}")

    return 0


def cmd_cluster(args):
    """Группирует проанализированные видео по темам."""
    analysis_dir = Path(args.analysis_dir)
    if not analysis_dir.exists():
        print(f"❌ Директория не найдена: {analysis_dir}", file=sys.stderr)
        return 1

    print(f"📚 Загрузка результатов анализа из: {analysis_dir}")
    videos_data = []
    for f in sorted(analysis_dir.glob("*_analysis.json")):
        with open(f, "r", encoding="utf-8") as fp:
            videos_data.append(json.load(fp))

    if not videos_data:
        print("❌ Нет файлов *_analysis.json", file=sys.stderr)
        return 1

    print(f"  ✅ Загружено видео: {len(videos_data)}")

    # Кластеризация
    videos_data = cluster_videos(videos_data, n_clusters=args.k)

    # Сохранение
    out_path = analysis_dir / "clusters.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(videos_data, f, ensure_ascii=False, indent=2)
    print(f"\n💾 Кластеры сохранены: {out_path}")

    # CSV для удобства
    df = pd.DataFrame([
        {
            "id": v.get("id"),
            "title": v.get("title", "")[:60],
            "cluster": v.get("cluster"),
            "topic_words": ", ".join(v.get("cluster_topic_words", [])[:5]),
        }
        for v in videos_data
    ])
    csv_path = analysis_dir / "clusters.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8")
    print(f"💾 CSV сохранён: {csv_path}")

    return 0


def cmd_search(args):
    """Ищет события по запросу."""
    analysis_dir = Path(args.analysis_dir)
    videos_data = []
    for f in sorted(analysis_dir.glob("*_analysis.json")):
        with open(f, "r", encoding="utf-8") as fp:
            videos_data.append(json.load(fp))

    if not videos_data:
        print("❌ Нет файлов анализа", file=sys.stderr)
        return 1

    print(f"🔎 Поиск: '{args.query}' в {len(videos_data)} видео")
    hits = search_events(videos_data, args.query)

    if not hits:
        print("❌ Ничего не найдено")
        return 0

    print(f"\n✅ Найдено совпадений: {len(hits)}\n")
    print(f"{'Время':<10} {'Тип':<12} {'Видео':<20} {'Текст/Описание'}")
    print("─" * 80)
    for h in hits[:args.limit]:
        time_str = f"{int(h['time'] // 60)}:{int(h['time'] % 60):02d}"
        text_short = h["text"][:50] + ("..." if len(h["text"]) > 50 else "")
        title_short = h["title"][:18] + ("..." if len(h["title"]) > 18 else "")
        print(f"{time_str:<10} {h['type']:<12} {title_short:<20} {text_short}")

    # Ссылки с временной меткой для YouTube
    if args.youtube_links:
        print("\n🔗 Ссылки для перехода:")
        for h in hits[:args.limit]:
            # Ищем URL в метаданных
            url = None
            for v in videos_data:
                if v.get("id") == h["video_id"]:
                    url = v.get("url")
                    break
            if url and "youtube.com" in url:
                t = int(h["time"])
                clean_url = url.split("&")[0]  # убираем лишние параметры
                print(f"  {clean_url}?t={t}s")

    return 0


def cmd_timeline(args):
    """Показывает временную шкалу событий для видео."""
    analysis_file = Path(args.analysis_file)
    if not analysis_file.exists():
        print(f"❌ Файл не найден: {analysis_file}", file=sys.stderr)
        return 1

    with open(analysis_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    timeline = data.get("timeline", [])
    title = data.get("title", data.get("id", "unknown"))
    duration = data.get("technical", {}).get("duration", 0)

    print(f"\n⏱  Временная шкала: {title}")
    print(f"   Длительность: {duration:.1f}s")
    print(f"   Всего событий: {len(timeline)}\n")

    if not timeline:
        print("  (событий не найдено)")
        return 0

    # Визуализация шкалы в консоли
    bar_width = 60
    print(f"  0s{'─' * bar_width}{duration:.0f}s")
    print(f"  │{'│'.join(['─'] * (bar_width - 1))}│")

    # Группируем события по времени (окно 5 сек)
    for ev in timeline[:args.limit]:
        t = ev["time"]
        pos = int((t / duration) * bar_width) if duration > 0 else 0
        pos = min(pos, bar_width - 1)
        marker = "●" if ev["type"] == "visual" else "◆"
        desc = ev["description"][:50]
        print(f"  {marker} {t:6.1f}s [{ev['type'][:6]}] {desc}")

    print(f"\n  ● — визуальное событие, ◆ — аудио (ключевое слово)")

    # Экспорт в JSON
    if args.output:
        out_path = Path(args.output)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({"title": title, "timeline": timeline}, f,
                      ensure_ascii=False, indent=2)
        print(f"\n💾 Шкала сохранена: {out_path}")

    return 0


# ============================================================
# 9. Главный CLI
# ============================================================
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Система анализа видеоданных: сбор, детекция, транскрипция, поиск",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Примеры:\n"
            "  # Скачать видео с YouTube\n"
            "  python video_analyzer.py download https://youtube.com/watch?v=XXX -o data/\n\n"
            "  # Проанализировать локальное видео\n"
            "  python video_analyzer.py analyze video.mp4 -o data/ --keywords 'ремонт,плитка'\n\n"
            "  # Сгруппировать проанализированные видео\n"
            "  python video_analyzer.py cluster data/ --k 5\n\n"
            "  # Поиск по событиям\n"
            "  python video_analyzer.py search data/ --query 'плитка' --youtube-links\n\n"
            "  # Показать временную шкалу\n"
            "  python video_analyzer.py timeline data/video_analysis.json\n"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── download ──
    p_dl = subparsers.add_parser("download", help="Скачать видео и метаданные")
    p_dl.add_argument("url", help="URL видео (YouTube, Rutube, VK Video и др.)")
    p_dl.add_argument("-o", "--output-dir", default="data/videos",
                      help="Папка для сохранения (по умолчанию data/videos)")

    # ── analyze ──
    p_an = subparsers.add_parser("analyze", help="Проанализировать видео")
    p_an.add_argument("video", help="Путь к видеофайлу")
    p_an.add_argument("-o", "--output-dir", default="data/analysis",
                      help="Папка для результатов")
    p_an.add_argument("--fps-sample", type=float, default=1.0,
                      help="Кадров в секунду для выборки (по умолчанию 1.0)")
    p_an.add_argument("--conf", type=float, default=0.4,
                      help="Порог уверенности YOLO (по умолчанию 0.4)")
    p_an.add_argument("--yolo-model", default="yolov8n.pt",
                      help="Модель YOLO (по умолчанию yolov8n.pt)")
    p_an.add_argument("--whisper-model", default="base",
                      choices=["tiny", "base", "small", "medium", "large"],
                      help="Модель Whisper (по умолчанию base)")
    p_an.add_argument("--language", default="ru",
                      help="Язык аудио (по умолчанию ru)")
    p_an.add_argument("--keywords",
                      help="Ключевые слова для шкалы через запятую")

    # ── cluster ──
    p_cl = subparsers.add_parser("cluster", help="Сгруппировать видео по темам")
    p_cl.add_argument("analysis_dir", help="Папка с файлами *_analysis.json")
    p_cl.add_argument("--k", type=int, default=5,
                      help="Число кластеров (по умолчанию 5)")

    # ── search ──
    p_sr = subparsers.add_parser("search", help="Поиск по событиям")
    p_sr.add_argument("analysis_dir", help="Папка с файлами *_analysis.json")
    p_sr.add_argument("--query", required=True, help="Поисковый запрос")
    p_sr.add_argument("--limit", type=int, default=20,
                      help="Максимум результатов (по умолчанию 20)")
    p_sr.add_argument("--youtube-links", action="store_true",
                      help="Показать ссылки YouTube с временной меткой")

    # ── timeline ──
    p_tl = subparsers.add_parser("timeline", help="Показать временную шкалу")
    p_tl.add_argument("analysis_file", help="Путь к файлу *_analysis.json")
    p_tl.add_argument("--limit", type=int, default=50,
                      help="Максимум событий (по умолчанию 50)")
    p_tl.add_argument("--output", help="Сохранить шкалу в JSON")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    commands = {
        "download": cmd_download,
        "analyze": cmd_analyze,
        "cluster": cmd_cluster,
        "search": cmd_search,
        "timeline": cmd_timeline,
    }
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())