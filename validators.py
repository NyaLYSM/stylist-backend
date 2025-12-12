# validators.py
import io
import os
import re
from typing import Tuple, Optional
from PIL import Image

# Простая длинная маска ключевых слов (можно дополнять)
CLOTHING_KEYWORDS = set("""
shirt tee t-shirt blouse polo sweater sweatshirt hoodie jumper tank top camisole tee-shirt
jeans trousers pants chinos joggers shorts skirt dress suit blazer coat jacket parka trench
raincoat rain jacket windbreaker bomber cardigan vest waistcoat blazer romper jumpsuit
sweatpants joggers leggings tights underwear bra briefs boxers lingerie swim swimsuit
bikini trunks robe kimono slippers sandals boots sneakers heels loafers oxfords derbies
moccasins trainers sandals flipflops cloak cape beret beanie cap hat scarf gloves belt tie
bowtie bow belt handbag purse satchel backpack wallet clutch earring necklace bracelet ring
watch sunglasses shades
""".split())

# Expand with common Russian words (small set — can be expanded)
CLOTHING_KEYWORDS.update({
    "футболк", "рубашк", "шорты", "джинс", "куртк", "пальто", "кофта", "свитер", "платье",
    "юбк", "ботинк", "сандал", "кроссовк", "тапочк", "белье", "майк", "жилет", "шляп",
    "шапк", "перчат", "ремень", "сумк", "рюкзак", "очки"
})

# Regex for allowed name tokens (letters, numbers, space, hyphen)
NAME_RE = re.compile(r"^[\w\s\-\.,()\"'&]+$", re.UNICODE)

MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB


def clean_name(name: str) -> str:
    s = name.strip()
    # Collapse multiple spaces
    s = re.sub(r'\s+', ' ', s)
    return s


def name_looks_like_clothing(name: str) -> bool:
    """Быстрая сигнатура — есть ли в имени ключевое слово одежды"""
    n = name.lower()
    # check substrings
    for kw in CLOTHING_KEYWORDS:
        if kw in n:
            return True
    return False


def validate_name(name: str) -> Tuple[bool, Optional[str]]:
    """Валидация строки названия вещи"""
    if not name or len(name.strip()) < 2:
        return False, "Название слишком короткое"
    if len(name) > 200:
        return False, "Название слишком длинное"
    if not NAME_RE.match(name):
        return False, "Название содержит недопустимые символы"
    if not name_looks_like_clothing(name):
        # не однозначно — можно вернуть предупреждение
        return False, "Название не похоже на предмет одежды"
    return True, None


def validate_image_bytes(data: bytes) -> Tuple[bool, Optional[str]]:
    """Проверяем размер и что это корректное изображение"""
    if not data:
        return False, "Нет данных изображения"
    if len(data) > MAX_IMAGE_BYTES:
        return False, "Файл слишком большой (макс 5 МБ)"
    try:
        im = Image.open(io.BytesIO(data))
        im.verify()
    except Exception:
        return False, "Невозможно открыть/распознать изображение"
    return True, None
