# utils/clip_client.py
import logging
import requests
from PIL import Image

# Настройка логгера
logger = logging.getLogger(__name__)

# === КОНФИГУРАЦИЯ ===
CLIP_SERVICE_URL = "http://127.0.0.1:8001"
# Модель для локальной загрузки (если есть ресурсы)
HF_MODEL_NAME = "openai/clip-vit-base-patch32"

# Глобальные переменные для кеширования модели (Lazy Loading)
_model = None
_processor = None
_device = None
_clip_loaded = False

def init_local_clip():
    """
    Загружает CLIP в память процесса, если установлены библиотеки transformers и torch.
    Это позволяет делать скоринг без внешних запросов.
    """
    global _model, _processor, _device, _clip_loaded
    
    if _clip_loaded:
        return True

    try:
        import torch
        from transformers import CLIPProcessor, CLIPModel
        
        logger.info("🧠 Loading CLIP model locally...")
        _device = "cuda" if torch.cuda.is_available() else "cpu"
        _model = CLIPModel.from_pretrained(HF_MODEL_NAME).to(_device)
        _processor = CLIPProcessor.from_pretrained(HF_MODEL_NAME)
        _model.eval() # Режим инференса
        _clip_loaded = True
        logger.info(f"✅ CLIP loaded on {_device}")
        return True
    except ImportError:
        logger.warning("⚠️ Transformers/Torch not installed. CLIP scoring will be disabled.")
        return False
    except Exception as e:
        logger.error(f"❌ Error loading CLIP: {e}")
        return False

def rate_image_relevance(image: Image.Image, product_name: str) -> float:
    """
    Оценивает (0-100), насколько картинка соответствует названию товара,
    отфильтровывая мусор (таблицы, упаковку, сложные аутфиты).
    """
    # 1. Если локальная модель не загружена, пробуем загрузить
    if not _clip_loaded:
        if not init_local_clip():
            return 50.0 # Нейтральная оценка, если CLIP нет

    try:
        import torch
        
        # Очищаем название для промпта (английский CLIP лучше понимает транслит или общие фразы, 
        # но мультиязычный справится и с русским. Для базы openai лучше добавить контекст).
        # Простой хак: добавляем "clothing item" чтобы задать контекст
        
        # ПОЗИТИВНЫЕ И НЕГАТИВНЫЕ КЛАССЫ
        # CLIP работает через сравнение: "На что это больше похоже?"
        choices = [
            f"photo of {product_name}, product view, clean background", # 0: То, что ищем (Target)
            "size chart, text table, infographics with numbers",        # 1: Таблицы (Мусор)
            "close-up fabric texture, macro shot",                      # 2: Текстуры (Мусор)
            "packaging box, plastic bag, delivery package",             # 3: Упаковка (Мусор)
            "full body outfit, messy background, street style, many items" # 4: Аутфит (где непонятно что продаем)
        ]
        
        # Подготовка данных
        inputs = _processor(
            text=choices, 
            images=image, 
            return_tensors="pt", 
            padding=True,
            truncation=True
        ).to(_device)

        # Инференс
        with torch.no_grad():
            outputs = _model(**inputs)
        
        # Получаем вероятности (softmax)
        logits_per_image = outputs.logits_per_image
        probs = logits_per_image.softmax(dim=1) # shape: [1, 5]
        
        # Score = вероятность того, что это наш товар (индекс 0)
        # Умножаем на 100 для удобства
        target_prob = probs[0][0].item()
        chart_prob = probs[0][1].item()
        
        # Доп. логика: Если вероятность "таблицы" (индекс 1) выше 10%, сильно штрафуем
        if chart_prob > 0.1:
            return 10.0
            
        return target_prob * 100.0

    except Exception as e:
        logger.error(f"⚠️ CLIP scoring failed: {e}")
        return 50.0

# --- Старые функции для совместимости (HTTP) ---

def clip_check_clothing(image_url: str) -> dict:
    """Оставляет старую логику запроса к внешнему сервису, если она нужна"""
    try:
        r = requests.post(
            f"{CLIP_SERVICE_URL}/check-clothing",
            json={"image_url": image_url},
            timeout=5
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {"ok": True} # Fallback
