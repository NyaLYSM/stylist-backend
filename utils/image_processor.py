from io import BytesIO
from PIL import Image
import logging

logger = logging.getLogger(__name__)

def create_center_crop(img: Image.Image, size: int = 800) -> Image.Image:
    """Центральный квадратный кроп"""
    width, height = img.size
    crop_size = min(width, height)
    
    left = (width - crop_size) // 2
    top = (height - crop_size) // 2
    right = left + crop_size
    bottom = top + crop_size
    
    cropped = img.crop((left, top, right, bottom))
    
    if crop_size > size:
        cropped = cropped.resize((size, size), Image.Resampling.LANCZOS)
    
    return cropped

def create_smart_crop(img: Image.Image, size: int = 800) -> Image.Image:
    """Умный кроп (упрощенная версия без тяжелых вычислений)"""
    # Для Render просто возвращаем центральный кроп
    return create_center_crop(img, size)

def create_tight_crop(img: Image.Image, size: int = 800) -> Image.Image:
    """Плотный кроп с минимальными отступами"""
    # Упрощенная версия - центральный кроп с немного меньшим размером
    width, height = img.size
    crop_size = int(min(width, height) * 0.9)  # 90% от минимальной стороны
    
    left = (width - crop_size) // 2
    top = (height - crop_size) // 2
    right = left + crop_size
    bottom = top + crop_size
    
    cropped = img.crop((left, top, right, bottom))
    
    if crop_size > size:
        cropped = cropped.resize((size, size), Image.Resampling.LANCZOS)
    
    return cropped

def create_enhanced_version(img: Image.Image, size: int = 800) -> Image.Image:
    """Версия с легким улучшением (упрощенная)"""
    from PIL import ImageEnhance
    
    cropped = create_center_crop(img, size)
    
    # Легкое улучшение качества
    try:
        enhancer = ImageEnhance.Sharpness(cropped)
        enhanced = enhancer.enhance(1.1)
        
        enhancer = ImageEnhance.Contrast(enhanced)
        enhanced = enhancer.enhance(1.05)
        
        return enhanced
    except:
        # Если не получилось, возвращаем оригинал
        return cropped

def generate_image_variants(img: Image.Image, output_size: int = 800) -> dict:
    """
    Генерирует 4 варианта обработки изображения
    ЛЕГКАЯ ВЕРСИЯ для Render (без тяжелых вычислений)
    """
    try:
        logger.info(f"🎨 Generating variants for image {img.size}")
        
        variants = {}
        
        # Вариант A: Оригинальный
        logger.info("  📸 Creating center crop...")
        variants["original"] = create_center_crop(img, output_size)
        
        # Вариант B: Умный кроп (пока = центральный)
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
    """Конвертирует PIL Image в bytes"""
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
