# clip_helper.py
import os
import numpy as np

try:
    import onnxruntime as rt
except Exception:
    rt = None

# Путь к onnx моделям (ты должен скачать эти файлы сам и положить в models/)
IMG_ONNX = os.path.join("models", "clip_image.onnx")
TXT_ONNX = os.path.join("models", "clip_text.onnx")

sess_img = None
sess_txt = None

def try_load():
    global sess_img, sess_txt
    if rt is None:
        return False
    if os.path.exists(IMG_ONNX) and os.path.exists(TXT_ONNX):
        sess_img = rt.InferenceSession(IMG_ONNX, providers=["CPUExecutionProvider"])
        sess_txt = rt.InferenceSession(TXT_ONNX, providers=["CPUExecutionProvider"])
        return True
    return False

def embed_image_np(image_np: np.ndarray) -> np.ndarray:
    """Принимаем уже подготовленный numpy array в формате модели"""
    if not sess_img:
        return None
    inputs = {sess_img.get_inputs()[0].name: image_np.astype(np.float32)}
    out = sess_img.run(None, inputs)[0]
    # normalize
    out = out / np.linalg.norm(out, axis=-1, keepdims=True)
    return out

def embed_texts(texts: list) -> np.ndarray:
    if not sess_txt:
        return None
    # Здесь ожидается, что модель принимает токенизированный вход — упрощённо:
    # В реальной сборке нужно подготовить токены (вместе с tokenizer).
    # Поэтому полноценно работающее ONNX решение требует токенайзера и соответствующей версии.
    return None

def image_vs_labels_score(image_np: np.ndarray, label_texts: list) -> float:
    """
    Ограниченная заглушка: если у тебя есть готовые text embeddings - сравнивай.
    В общем случае реализация CLIP ONNX требует токенайзера и подготовленных текстовых эмбеддингов.
    """
    return 0.0

# Попытайся загрузить при импорте
_loaded = try_load()
