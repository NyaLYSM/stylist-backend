# utils/scraper.py

from curl_cffi import requests as crequests
from bs4 import BeautifulSoup
import re
import logging

logger = logging.getLogger(__name__)

# Математическая карта серверов WB (обновленная)
def get_wb_host(vol: int) -> str:
    if 0 <= vol <= 143: return "basket-01.wbbasket.ru"
    if 144 <= vol <= 287: return "basket-02.wbbasket.ru"
    if 288 <= vol <= 431: return "basket-03.wbbasket.ru"
    if 432 <= vol <= 719: return "basket-04.wbbasket.ru"
    if 720 <= vol <= 1007: return "basket-05.wbbasket.ru"
    if 1008 <= vol <= 1061: return "basket-06.wbbasket.ru"
    if 1062 <= vol <= 1115: return "basket-07.wbbasket.ru"
    if 1116 <= vol <= 1169: return "basket-08.wbbasket.ru"
    if 1170 <= vol <= 1313: return "basket-09.wbbasket.ru"
    if 1314 <= vol <= 1601: return "basket-10.wbbasket.ru"
    if 1602 <= vol <= 1655: return "basket-11.wbbasket.ru"
    if 1656 <= vol <= 1919: return "basket-12.wbbasket.ru"
    if 1920 <= vol <= 2045: return "basket-13.wbbasket.ru"
    if 2046 <= vol <= 2189: return "basket-14.wbbasket.ru"
    if 2190 <= vol <= 2405: return "basket-15.wbbasket.ru"
    if 2406 <= vol <= 2621: return "basket-16.wbbasket.ru"
    if 2622 <= vol <= 2837: return "basket-17.wbbasket.ru"
    if 2838 <= vol <= 3053: return "basket-18.wbbasket.ru"
    if 3054 <= vol <= 3269: return "basket-19.wbbasket.ru"
    if 3270 <= vol <= 3485: return "basket-20.wbbasket.ru"
    if 3486 <= vol <= 3701: return "basket-21.wbbasket.ru"
    return "basket-22.wbbasket.ru"

def get_marketplace_data(url: str):
    """
    Возвращает (image_url, title) для любого маркетплейса.
    """
    
    # 1. WILDBERRIES (Быстрый путь через API/Математику)
    if "wildberries" in url or "wb.ru" in url:
        try:
            match = re.search(r'catalog/(\d+)', url)
            if match:
                nm_id = int(match.group(1))
                vol = nm_id // 100000
                part = nm_id // 1000
                host = get_wb_host(vol)
                image_url = f"https://{host}/vol{vol}/part{part}/{nm_id}/images/big/1.jpg"
                return image_url, "Wildberries Item"
        except Exception as e:
            logger.error(f"WB Math failed: {e}")

    # 2. УНИВЕРСАЛЬНЫЙ ПАРСЕР (Ozon, Lamoda, etc.)
    # Используем curl_cffi чтобы притвориться Chrome 120
    try:
        response = crequests.get(
            url, 
            impersonate="chrome120", 
            timeout=15,
            allow_redirects=True
        )
        
        if response.status_code != 200:
            logger.error(f"Page load failed: {response.status_code}")
            return None, None

        soup = BeautifulSoup(response.content, "lxml")

        # Ищем картинку (OG Tag)
        og_image = soup.find("meta", property="og:image")
        image_url = og_image["content"] if og_image else None
        
        # Ищем название
        og_title = soup.find("meta", property="og:title")
        title = og_title["content"] if og_title else soup.title.string

        return image_url, title

    except Exception as e:
        logger.error(f"Scraper error: {e}")
        return None, None
