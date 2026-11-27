import hashlib
import re

import ftfy
from itemadapter import ItemAdapter
from scrapy.exceptions import DropItem


class CleaningPipeline:
    """ftfy + нормализация пробелов."""

    def process_item(self, item, *args, **kwargs):
        a = ItemAdapter(item)
        for field in a.field_names():
            value = a.get(field)
            if isinstance(value, str):
                value = ftfy.fix_text(value)
                value = re.sub(r"\s+", " ", value).strip()
                a[field] = value
            elif isinstance(value, list):
                a[field] = [
                    re.sub(r"\s+", " ", ftfy.fix_text(v)).strip()
                    for v in value if isinstance(v, str) and v.strip()
                ]
        return item


class DuplicationPipeline:
    """Дедупликация по URL."""

    def __init__(self):
        self.seen = set()

    def process_item(self, item, *args, **kwargs):
        a = ItemAdapter(item)
        url = a.get("url")
        if not url:
            raise DropItem("нет url")
        key = hashlib.md5(url.encode("utf-8")).hexdigest()
        if key in self.seen:
            raise DropItem(f"дубликат: {url}")
        self.seen.add(key)
        return item


class ValidationPipeline:
    """Проверка обязательных полей."""

    REQUIRED = {
        "NewsItem": ["title", "url"],
        "ProductItem": ["title", "url", "price"],
    }

    def process_item(self, item, *args, **kwargs):
        a = ItemAdapter(item)
        required = self.REQUIRED.get(type(item).__name__, ["title", "url"])
        for field in required:
            v = a.get(field)
            if v is None or (isinstance(v, str) and not v.strip()):
                raise DropItem(f"нет обязательного поля '{field}': {dict(a)}")
        return item