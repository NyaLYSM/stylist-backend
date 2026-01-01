# clip_service.py
# Запускать отдельно: python clip_service.py
# Будет работать на порту 8001

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import torch
from PIL import Image
import requests
from io import BytesIO
import uvicorn
import logging

# Импортируем CLIP
try:
    import clip
except ImportError:
    print("⚠️ CLIP не установлен. Установите: pip install git+https://github.com/openai/CLIP.git")
    exit(1)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="CLIP Service", version="2.0")

# === Глобальная модель (загружается один раз) ===
MODEL = None
PREPROCESS = None
DEVICE = None

# === Категории одежды ===
CLOTHING_CATEGORIES = {
    "ru": [
        "футболка", "рубашка", "свитер", "худи", "кардиган", "жилет",
        "куртка", "пальто", "пуховик", "ветровка", "бомбер",
        "джинсы", "брюки", "штаны", "шорты", "юбка", "леггинсы",
        "платье", "сарафан", "комбинезон",
        "кроссовки", "ботинки", "туфли", "сапоги", "сандалии",
        "кепка", "шапка", "шляпа", "берет",
        "сумка", "рюкзак", "клатч",
        "шарф", "перчатки", "ремень", "очки"
    ],
    "en": [
        "t-shirt", "shirt", "sweater", "hoodie", "cardigan", "vest",
        "jacket", "coat", "down jacket", "windbreaker", "bomber",
        "jeans", "trousers", "pants", "shorts", "skirt", "leggings",
        "dress", "sundress", "jumpsuit",
        "sneakers", "boots", "shoes", "sandals",
        "cap", "hat", "beanie", "beret",
        "bag", "backpack", "clutch",
        "scarf", "gloves", "belt", "glasses"
    ]
}

# === Стили и характеристики ===
STYLES = {
    "ru": ["классический", "спортивный", "casual", "деловой", "уличный", "винтажный", "оверсайз"],
    "en": ["classic", "sporty", "casual", "business", "streetwear", "vintage", "oversized"]
}

COLORS = {
    "ru": ["черный", "белый", "синий", "красный", "зелёный", "жёлтый", "серый", "бежевый", "коричневый", "розовый", "фиолетовый", "оранжевый"],
    "en": ["black", "white", "blue", "red", "green", "yellow", "gray", "beige", "brown", "pink", "purple", "orange"]
}

PATTERNS = {
    "ru": ["однотонный", "в полоску", "в клетку", "с принтом", "с узором"],
    "en": ["solid", "striped", "checkered", "printed", "patterned"]
}

@app.on_event("startup")
def load_model():
    """Загрузка CLIP модели при старте сервиса"""
    global MODEL, PREPROCESS, DEVICE
    
    logger.info("🔄 Загрузка CLIP модели...")
    
    DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info(f"📱 Используется устройство: {DEVICE}")
    
    # Загружаем модель ViT-B/32 (легкая и быстрая)
    MODEL, PREPROCESS = clip.load("ViT-B/32", device=DEVICE)
    
    logger.info("✅ CLIP модель загружена успешно!")

def download_image(url: str) -> Image.Image:
    """Скачивает изображение по URL"""
    try:
        response = requests.get(url, timeout=10, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        response.raise_for_status()
        return Image.open(BytesIO(response.content)).convert("RGB")
    except Exception as e:
        raise HTTPException(400, f"Не удалось загрузить изображение: {str(e)}")

def classify_with_clip(image: Image.Image, categories: list, language: str = "ru") -> dict:
    """
    Классифицирует изображение по списку категорий
    Возвращает: {"category": "название", "confidence": 0.95}
    """
    # Подготовка изображения
    image_input = PREPROCESS(image).unsqueeze(0).to(DEVICE)
    
    # Подготовка текстовых промптов
    if language == "ru":
        text_prompts = [f"фотография {cat}" for cat in categories]
    else:
        text_prompts = [f"a photo of {cat}" for cat in categories]
    
    text_inputs = clip.tokenize(text_prompts).to(DEVICE)
    
    # Получаем эмбеддинги
    with torch.no_grad():
        image_features = MODEL.encode_image(image_input)
        text_features = MODEL.encode_text(text_inputs)
        
        # Нормализуем
        image_features /= image_features.norm(dim=-1, keepdim=True)
        text_features /= text_features.norm(dim=-1, keepdim=True)
        
        # Вычисляем сходство
        similarity = (100.0 * image_features @ text_features.T).softmax(dim=-1)
    
    # Находим лучшее совпадение
    values, indices = similarity[0].topk(3)
    
    results = []
    for i in range(3):
        results.append({
            "category": categories[indices[i].item()],
            "confidence": values[i].item()
        })
    
    return results

# === API Endpoints ===

class ImageRequest(BaseModel):
    image_url: str

class ClothingCheckRequest(BaseModel):
    image_url: str
    title: str = ""

@app.post("/check-clothing")
def check_clothing(request: ClothingCheckRequest):
    """
    Проверяет, является ли изображение одеждой (совместимость со старым API)
    """
    try:
        image = download_image(request.image_url)
        
        # Проверяем, это одежда или нет
        categories = ["clothing item", "person wearing clothes", "not clothing"]
        results = classify_with_clip(image, categories, language="en")
        
        is_clothing = results[0]["category"] in ["clothing item", "person wearing clothes"]
        confidence = results[0]["confidence"]
        
        return {
            "ok": is_clothing and confidence > 0.5,
            "confidence": confidence,
            "reason": "Изображение содержит одежду" if is_clothing else "Изображение не содержит одежду"
        }
    except Exception as e:
        logger.error(f"Error in check-clothing: {e}")
        return {"ok": False, "reason": str(e)}

@app.post("/classify-clothing")
def classify_clothing_endpoint(request: ImageRequest):
    """
    Определяет тип одежды на изображении
    Возвращает: тип, цвет, стиль
    """
    try:
        image = download_image(request.image_url)
        
        # 1. Определяем тип одежды
        clothing_type = classify_with_clip(image, CLOTHING_CATEGORIES["ru"], "ru")
        
        # 2. Определяем цвет
        color_result = classify_with_clip(image, COLORS["ru"], "ru")
        
        # 3. Определяем стиль (опционально)
        style_result = classify_with_clip(image, STYLES["ru"], "ru")
        
        # 4. Определяем паттерн
        pattern_result = classify_with_clip(image, PATTERNS["ru"], "ru")
        
        return {
            "success": True,
            "type": clothing_type[0],
            "color": color_result[0],
            "style": style_result[0],
            "pattern": pattern_result[0],
            "alternatives": {
                "types": clothing_type[:3],
                "colors": color_result[:3],
                "styles": style_result[:3]
            }
        }
    except Exception as e:
        logger.error(f"Error in classify-clothing: {e}")
        raise HTTPException(500, f"Ошибка классификации: {str(e)}")

@app.post("/generate-name")
def generate_clothing_name(request: ImageRequest):
    """
    Генерирует умное название для одежды
    Пример: "Синие брюки палаццо", "Черная футболка оверсайз"
    """
    try:
        image = download_image(request.image_url)
        
        # Получаем все характеристики
        clothing_type = classify_with_clip(image, CLOTHING_CATEGORIES["ru"], "ru")
        color_result = classify_with_clip(image, COLORS["ru"], "ru")
        style_result = classify_with_clip(image, STYLES["ru"], "ru")
        pattern_result = classify_with_clip(image, PATTERNS["ru"], "ru")
        
        # Формируем название
        type_name = clothing_type[0]["category"]
        color_name = color_result[0]["category"]
        style_name = style_result[0]["category"]
        pattern_name = pattern_result[0]["category"]
        
        # Логика формирования названия
        name_parts = []
        
        # Добавляем цвет (если уверенность > 0.3)
        if color_result[0]["confidence"] > 0.3:
            name_parts.append(color_name.capitalize())
        
        # Добавляем паттерн (если не "однотонный" и уверенность > 0.4)
        if pattern_name != "однотонный" and pattern_result[0]["confidence"] > 0.4:
            name_parts.append(pattern_name)
        
        # Добавляем тип одежды
        name_parts.append(type_name)
        
        # Добавляем стиль (если уверенность > 0.35)
        if style_result[0]["confidence"] > 0.35 and style_name not in ["классический"]:
            name_parts.append(style_name)
        
        final_name = " ".join(name_parts)
        
        return {
            "success": True,
            "name": final_name,
            "confidence": clothing_type[0]["confidence"],
            "details": {
                "type": type_name,
                "color": color_name,
                "style": style_name,
                "pattern": pattern_name
            }
        }
    except Exception as e:
        logger.error(f"Error in generate-name: {e}")
        raise HTTPException(500, f"Ошибка генерации названия: {str(e)}")

@app.get("/health")
def health_check():
    """Проверка работоспособности сервиса"""
    return {
        "status": "ok",
        "model_loaded": MODEL is not None,
        "device": str(DEVICE) if DEVICE else "unknown"
    }

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="info")
