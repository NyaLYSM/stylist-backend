# utils/validators.py - ИДЕАЛЬНАЯ ВЕРСИЯ
import io
import re
from typing import Tuple, Optional
from PIL import Image

# ============================================================================
# КОНСТАНТЫ
# ============================================================================
MAX_IMAGE_BYTES = 3 * 1024 * 1024  # 10 MB (согласовано с wardrobe.py)

# ============================================================================
# РАСШИРЕННЫЙ СПИСОК КЛЮЧЕВЫХ СЛОВ (Русский + Английский)
# ============================================================================
CLOTHING_KEYWORDS = set("""
shirt tee t-shirt blouse polo sweater sweatshirt hoodie jumper tank top camisole
jeans trousers pants chinos joggers shorts skirt dress suit blazer coat jacket parka
trench raincoat windbreaker bomber cardigan vest waistcoat romper jumpsuit overalls
sweatpants leggings tights underwear bra briefs boxers lingerie swim swimsuit bikini
trunks robe kimbo slippers sandals boots sneakers heels loafers oxfords derbies
moccasins trainers flipflops cloak cape poncho beret beanie cap hat scarf gloves
mittens belt tie bowtie sash handbag purse satchel backpack wallet clutch tote
earring necklace bracelet ring watch sunglasses shades glasses socks stockings
jersey tracksuit
""".split())

# Русские ключевые слова (максимально полный список)
CLOTHING_KEYWORDS.update({
    # Верх
    "футболк", "майк", "рубаш", "блуз", "свитер", "кофт", "толстовк", "худи", "жилет",
    "безрукавк", "топ", "корсет", "боди", "водолазк", "гольф", "туник", "пиджак",
    "жакет", "кардиган", "джемпер", "регл", "поло", "лонгслив",
    
    # Низ
    "джинс", "брюк", "штан", "шорт", "бермуд", "юбк", "легинс", "лосин", "треник",
    "спортивк", "чинос", "карго", "капри", "кюлот",
    
    # Верхняя одежда
    "курт", "пальто", "плащ", "парк", "пуховик", "ветровк", "бомбер", "тренч", "дубленк",
    "шуб", "анорак", "косух", "дождевик", "ветров", "жилетк",
    
    # Платья и комбинезоны
    "плать", "сарафан", "комбинезон", "комбез", "ромпер", "костюм", "двойк", "тройк",
    
    # Нижнее белье и купальники
    "белье", "трус", "бюстгальтер", "лифчик", "боксер", "стринг", "слип", "купальник",
    "плавк", "бикини", "монокини", "пижам", "халат", "ночнушк", "сорочк",
    
    # Обувь
    "ботинк", "сапог", "туфл", "кроссовк", "кед", "сланц", "шлепанц", "сандал",
    "босоножк", "мокасин", "лоуфер", "челси", "броги", "оксфорд", "дерби", "балетк",
    "эспадриль", "тапоч", "угги", "полусапог", "ботильон", "гриндерс",
    
    # Аксессуары
    "шапк", "берет", "кепк", "бейсболк", "панам", "шляп", "снуд", "шарф", "платок",
    "бандан", "перчатк", "варежк", "рукавиц", "ремень", "пояс", "подтяжк", "галстук",
    "бабочк", "запонк", "часы", "браслет", "колье", "бусы", "серьг", "кольц",
    "цепочк", "кулон", "брош", "заколк", "ободок", "резинк",
    
    # Сумки
    "сумк", "рюкзак", "портфел", "кошелек", "клатч", "тот", "шоппер", "месседж",
    "поясн", "бананк", "косметичк",
    
    # Очки и другое
    "очки", "линз", "солнцезащит", "носк", "гольф", "колготк", "чулк", "гетр",
    "гамаш", "леггинс", "трико",
    
    # Спортивное
    "спорт", "треник", "олимпийк", "винд", "рашгард", "компресс", "термобелье",
    "горнолыж", "сноуборд", "велосипед", "беговые", "футбольн", "баскетбольн",
    
    # Дополнительные слова
    "одежд", "вещь", "вещи", "наряд", "outfit", "look", "style", "fashion",
    "wear", "garment", "apparel", "attire", "clothing"
})

# Regex для допустимых символов
NAME_RE = re.compile(r'^[\w\s\-\.,()\"\'&/№+]+$', re.UNICODE)

# Единый размер файла (10 МБ как в wardrobe.py)
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB


def clean_name(name: str) -> str:
    """Очистка названия от лишних пробелов"""
    s = name.strip()
    s = re.sub(r'\s+', ' ', s)  # Схлопываем множественные пробелы
    return s


def name_looks_like_clothing(name: str) -> bool:
    """
    Проверка, похоже ли название на предмет одежды.
    Ищет любое ключевое слово как подстроку.
    """
    n = name.lower()
    
    # Проверяем каждое ключевое слово
    for kw in CLOTHING_KEYWORDS:
        if kw in n:
            return True
    
    # Дополнительная проверка: если есть цифры + буквы (артикулы товаров)
    # Например: "Футболка XL 2024" или "Джинсы 32/34"
    if re.search(r'\d', n) and re.search(r'[a-zа-яё]', n, re.IGNORECASE):
        # Если есть и цифры и буквы, скорее всего это товар
        return True
    
    return False


def validate_name(name: str) -> Tuple[bool, Optional[str]]:
    """
    Валидация названия вещи.
    Возвращает (True, None) если валидно, иначе (False, error_message)
    """
    # Базовые проверки
    if not name or not name.strip():
        return False, "Название не может быть пустым"
    
    cleaned = clean_name(name)
    
    # Проверка длины
    if len(cleaned) < 2:
        return False, "Название слишком короткое (минимум 2 символа)"
    
    if len(cleaned) > 200:
        return False, "Название слишком длинное (максимум 200 символов)"
    
    # Проверка допустимых символов
    if not NAME_RE.match(cleaned):
        return False, "Название содержит недопустимые символы"
    
    # Проверка на ключевые слова одежды
    if not name_looks_like_clothing(cleaned):
        return False, "Название не похоже на предмет одежды"
    
    return True, None


def validate_image_bytes(data: bytes) -> Tuple[bool, Optional[str]]:
    """
    Проверка изображения: размер и валидность.
    Возвращает (True, None) если валидно, иначе (False, error_message)
    """
    if not data:
        return False, "Нет данных изображения"
    
    # Проверка размера (10 МБ)
    if len(data) > MAX_IMAGE_BYTES:
        max_mb = MAX_IMAGE_BYTES / (1024 * 1024)
        return False, f"Файл слишком большой (максимум {max_mb:.0f} МБ)"
    
    # Проверка что это валидное изображение
    try:
        im = Image.open(io.BytesIO(data))
        im.verify()
        
        # Дополнительная проверка формата
        if im.format not in ['JPEG', 'PNG', 'GIF', 'WEBP', 'BMP']:
            return False, f"Неподдерживаемый формат изображения: {im.format}"
        
    except Exception as e:
        return False, f"Невозможно открыть изображение: {str(e)}"
    
    return True, None


# ============================================================================
# ДОПОЛНИТЕЛЬНЫЕ УТИЛИТЫ
# ============================================================================

def suggest_name_from_url(url: str) -> str:
    """
    Попытка извлечь название товара из URL маркетплейса.
    Используется как fallback, если пользователь не ввел название.
    """
    # Примеры URL:
    # https://www.wildberries.ru/catalog/12345/detail.aspx?targetUrl=GP
    # https://www.ozon.ru/product/krossovki-nike-air-max-270-123456789/
    
    try:
        from urllib.parse import urlparse, unquote
        parsed = urlparse(url)
        path = unquote(parsed.path)
        
        # Убираем /product/, /catalog/, /detail и т.д.
        path = re.sub(r'/(product|catalog|detail|item)/', '', path, flags=re.IGNORECASE)
        
        # Извлекаем последний сегмент пути
        segments = [s for s in path.split('/') if s and not s.isdigit()]
        if segments:
            name = segments[-1]
            # Заменяем дефисы на пробелы
            name = name.replace('-', ' ').replace('_', ' ')
            # Капитализируем
            name = name.title()
            return name[:100]  # Ограничиваем длину
    except:
        pass
    
    return "Товар"  # Дефолтное название

