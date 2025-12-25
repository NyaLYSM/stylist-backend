# utils/scraper.py

import requests
from bs4 import BeautifulSoup
import logging

# Притворяемся обычным браузером Chrome, чтобы сайты (WB, Ozon) не блокировали
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
}

def parse_marketplace_url(url: str):
    """
    Возвращает (image_url, title) или выбрасывает ошибку.
    Пытается найти Open Graph теги, которые есть у 99% магазинов.
    """
    try:
        # 1. Загружаем страницу
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        
        # 2. Парсим HTML
        soup = BeautifulSoup(response.content, "lxml") # lxml быстрее стандартного html.parser

        # 3. Ищем картинку (og:image)
        # Это стандарт для соцсетей, есть на WB, Lamoda и др.
        og_image = soup.find("meta", property="og:image")
        image_url = og_image["content"] if og_image else None

        # Если og:image нет, пробуем twitter:image (иногда бывает)
        if not image_url:
            twitter_img = soup.find("meta", name="twitter:image")
            image_url = twitter_img["content"] if twitter_img else None

        # 4. Ищем название (og:title)
        og_title = soup.find("meta", property="og:title")
        title = og_title["content"] if og_title else None
        
        # Если заголовка нет, берем <title> страницы
        if not title:
            title = soup.title.string if soup.title else "Покупка"

        # Очистка названия от мусора (например "Купить Брюки... в интернет магазине")
        if title:
            # Оставляем только первую часть до разделителей, часто это помогает очистить имя
            for sep in ["|", "—", "-", "купить", "цена"]:
                if sep in title.lower():
                    # Не рубим слишком агрессивно, это опционально
                    pass 
            title = title.strip()

        if not image_url:
            raise ValueError("Не удалось найти изображение товара на странице")

        return image_url, title

    except Exception as e:
        logging.error(f"Scraping error for {url}: {e}")
        # Если парсинг не удался, возвращаем None, чтобы внешний код обработал это
        raise e
