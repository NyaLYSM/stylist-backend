# utils/image_processor.py
import uuid
from io import BytesIO
from PIL import Image, ImageFilter, ImageEnhance
import logging

logger = logging.getLogger(__name__)

def create_center_crop(img: Image.Image, size: int = 800) -> Image.Image:
    """
    Вариант A: Центральный квадратный кроп
    """
    width, height = img.size
    
    # Определяем квадратную область
    crop_size = min(width, height)
    
    left = (width - crop_size) // 2
    top = (height - crop_size) // 2
    right = left + crop_size
    bottom = top + crop_size
    
    cropped = img.crop((left, top, right, bottom))
    
    # Ресайзим до нужного размера
    if crop_size > size:
        cropped = cropped.resize((size, size), Image.Resampling.LANCZOS)
    
    return cropped

def create_smart_crop(img: Image.Image, size: int = 800) -> Image.Image:
    """
    Вариант B: Умный кроп с фокусом на объект
    Использует детекцию краев для поиска интересной области
    """
    width, height = img.size
    
    # Конвертируем в grayscale для анализа
    gray = img.convert('L')
    
    # Применяем фильтр краев
    edges = gray.filter(ImageFilter.FIND_EDGES)
    
    # Увеличиваем контраст для лучшей детекции
    enhancer = ImageEnhance.Contrast(edges)
    edges = enhancer.enhance(2.0)
    
    # Ищем область с максимальной концентрацией краев
    # Делим изображение на сетку 3x3 и ищем самую "интересную" область
    grid_size = 3
    cell_w = width // grid_size
    cell_h = height // grid_size
    
    max_activity = 0
    best_cell = (1, 1)  # По умолчанию центр
    
    for i in range(grid_size):
        for j in range(grid_size):
            cell = edges.crop((
                j * cell_w,
                i * cell_h,
                (j + 1) * cell_w,
                (i + 1) * cell_h
            ))
            # Считаем сумму пикселей (активность)
            activity = sum(cell.getdata())
            
            if activity > max_activity:
                max_activity = activity
                best_cell = (i, j)
    
    # Создаём кроп вокруг найденной области
    cell_i, cell_j = best_cell
    crop_size = min(width, height)
    
    # Центр найденной ячейки
    center_x = cell_j * cell_w + cell_w // 2
    center_y = cell_i * cell_h + cell_h // 2
    
    # Вычисляем границы кропа
    left = max(0, center_x - crop_size // 2)
    top = max(0, center_y - crop_size // 2)
    right = min(width, left + crop_size)
    bottom = min(height, top + crop_size)
    
    # Корректируем если вышли за границы
    if right - left < crop_size:
        left = max(0, right - crop_size)
    if bottom - top < crop_size:
        top = max(0, bottom - crop_size)
    
    cropped = img.crop((left, top, right, bottom))
    
    if cropped.size[0] > size:
        cropped = cropped.resize((size, size), Image.Resampling.LANCZOS)
    
    return cropped

def create_tight_crop(img: Image.Image, size: int = 800, margin: int = 20) -> Image.Image:
    """
    Вариант C: Плотный кроп по границам объекта
    Убирает максимум пустого пространства
    """
    # Конвертируем в grayscale
    gray = img.convert('L')
    
    # Применяем threshold для бинаризации
    threshold = 240  # Считаем светлые пиксели фоном
    
    # Ищем границы непустой области
    pixels = gray.load()
    width, height = gray.size
    
    # Ищем границы объекта
    min_x, min_y = width, height
    max_x, max_y = 0, 0
    
    for y in range(height):
        for x in range(width):
            if pixels[x, y] < threshold:  # Не фон
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
    
    # Добавляем отступы
    min_x = max(0, min_x - margin)
    min_y = max(0, min_y - margin)
    max_x = min(width, max_x + margin)
    max_y = min(height, max_y + margin)
    
    # Делаем квадратным
    crop_w = max_x - min_x
    crop_h = max_y - min_y
    crop_size = max(crop_w, crop_h)
    
    # Центрируем
    center_x = (min_x + max_x) // 2
    center_y = (min_y + max_y) // 2
    
    left = max(0, center_x - crop_size // 2)
    top = max(0, center_y - crop_size // 2)
    right = min(width, left + crop_size)
    bottom = min(height, top + crop_size)
    
    cropped = img.crop((left, top, right, bottom))
    
    if cropped.size[0] > size:
        cropped = cropped.resize((size, size), Image.Resampling.LANCZOS)
    
    return cropped

def create_enhanced_version(img: Image.Image, size: int = 800) -> Image.Image:
    """
    Вариант D: Улучшенная версия с повышением качества
    Применяет легкую обработку для улучшения вида
    """
    # Центральный кроп
    cropped = create_center_crop(img, size)
    
    # Повышаем резкость
    enhancer = ImageEnhance.Sharpness(cropped)
    enhanced = enhancer.enhance(1.2)
    
    # Слегка повышаем контраст
    enhancer = ImageEnhance.Contrast(enhanced)
    enhanced = enhancer.enhance(1.1)
    
    # Слегка повышаем насыщенность
    enhancer = ImageEnhance.Color(enhanced)
    enhanced = enhancer.enhance(1.05)
    
    return enhanced

def generate_image_variants(img: Image.Image, output_size: int = 800) -> dict:
    """
    Генерирует 4 варианта обработки изображения
    
    Возвращает словарь с PIL Image объектами:
    {
        "original": Image,
        "smart_crop": Image,
        "tight_crop": Image,
        "enhanced": Image
    }
    """
    try:
        logger.info(f"🎨 Generating variants for image {img.size}")
        
        variants = {}
        
        # Вариант A: Оригинальный центральный кроп
        logger.info("  📸 Creating center crop...")
        variants["original"] = create_center_crop(img, output_size)
        
        # Вариант B: Умный кроп
        logger.info("  🎯 Creating smart crop...")
        variants["smart_crop"] = create_smart_crop(img, output_size)
        
        # Вариант C: Плотный кроп
        logger.info("  ✂️ Creating tight crop...")
        variants["tight_crop"] = create_tight_crop(img, output_size)
        
        # Вариант D: Улучшенная версия
        logger.info("  ✨ Creating enhanced version...")
        variants["enhanced"] = create_enhanced_version(img, output_size)
        
        logger.info(f"✅ Generated {len(variants)} variants")
        
        return variants
        
    except Exception as e:
        logger.error(f"❌ Error generating variants: {e}")
        # В случае ошибки возвращаем только оригинал
        return {"original": create_center_crop(img, output_size)}

def convert_variant_to_bytes(img: Image.Image, format: str = "JPEG", quality: int = 85) -> bytes:
    """
    Конвертирует PIL Image в bytes для сохранения
    """
    output = BytesIO()
    
    # Конвертируем в RGB если нужно
    if img.mode in ("RGBA", "P", "LA", "L"):
        rgb_img = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode in ("RGBA", "LA"):
            rgb_img.paste(img, mask=img.split()[-1])
        else:
            rgb_img.paste(img)
        img = rgb_img
    
    img.save(output, format=format, quality=quality, optimize=True)
    return output.getvalue()
