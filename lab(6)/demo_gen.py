#генерация тестового датасета
import json
import random

topics = {
    "спорт": ["футбол", "матч", "победа", "команда", "игрок", "тренер", "чемпионат", "голл"],
    "политика": ["президент", "закон", "парламент", "выборы", "депутат", "правительство"],
    "технологии": ["нейросеть", "python", "алгоритм", "данные", "модель", "обучение", "ai"],
    "экономика": ["рубль", "инфляция", "банк", "курс", "рынок", "компания", "бизнес"],
    "культура": ["театр", "фильм", "книга", "музей", "выставка", "концерт", "художник"],
}

docs = []
for topic, words in topics.items():
    for _ in range(60):  # 60 документов на тему = 300 всего
        n_words = random.randint(30, 80)
        text = " ".join(random.choices(words, k=n_words))
        # Добавляем немного шума
        noise = random.choices(["и", "в", "на", "с", "по", "для"], k=10)
        text += " " + " ".join(noise)
        docs.append({"title": f"{topic}_{_}", "text": text})

random.shuffle(docs)
with open("demo_news.json", "w", encoding="utf-8") as f:
    json.dump(docs, f, ensure_ascii=False, indent=2)
print(f"✅ Создан demo_news.json с {len(docs)} документами")