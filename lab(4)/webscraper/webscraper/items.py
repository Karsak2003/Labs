# Define here the models for your scraped items
#
# See documentation in:
# https://docs.scrapy.org/en/latest/topics/items.html

from dataclasses import dataclass
import scrapy


class NewsItem(scrapy.Item):
    """Элемент новостной статьи."""
    title = scrapy.Field()
    url = scrapy.Field()
    date = scrapy.Field()
    author = scrapy.Field()
    summary = scrapy.Field()
    tags = scrapy.Field()
    source = scrapy.Field()


class ProductItem(scrapy.Item):
    """Элемент товара."""
    title = scrapy.Field()
    url = scrapy.Field()
    price = scrapy.Field()
    old_price = scrapy.Field()
    rating = scrapy.Field()
    reviews_count = scrapy.Field()
    category = scrapy.Field()
    image_url = scrapy.Field()
    source = scrapy.Field()