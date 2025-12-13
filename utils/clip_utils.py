import torch
import open_clip 
from PIL import Image
from typing import Optional, Tuple

device = "cuda" if torch.cuda.is_available() else "cpu"

MODEL, PREPROCESS = open_clip.create_model_and_transforms(
    model_name="ViT-B-32",          # Модель ViT-B/32 в нотации open_clip
    pretrained='openai',            # Используем веса, обученные OpenAI
    device=device
)

MODEL.eval()

CLOTHES = [
    "t-shirt", "shirt", "jeans", "shorts", "jacket", "coat", "dress", "skirt",
    "hoodie", "sweatshirt", "sneakers", "boots", "shoes", "polo", "suit",
    "trousers", "pants", "cardigan", "blazer", "sweater", "tie", "scarf",
    "cap", "hat", "bag", "backpack", "belt", "underwear", "bra", "swimsuit",
    "vest"
]

def load_image(url_or_file: str, is_file=False):
    try:
        if is_file:
            return Image.open(url_or_file).convert("RGB")
        resp = requests.get(url_or_file, timeout=10)
        resp.raise_for_status()
        return Image.open(BytesIO(resp.content)).convert("RGB")
    except Exception:
        return None

def clip_is_clothing(image: Image.Image):
    """Проверяем, что на фото именно одежда, а не человек/пляж/собака."""
    texts = [f"a photo of {c}" for c in CLOTHES]
    text_tokens = clip.tokenize(texts).to(device)

    image_tensor = PREPROCESS(image).unsqueeze(0).to(device)
    with torch.no_grad():
        logits_per_image, _ = MODEL(image_tensor, text_tokens)
        probs = logits_per_image.softmax(dim=-1).cpu().numpy()[0]

    # Чем выше порог, тем жёстче фильтр
    best = max(probs)

    return best > 0.20, texts[int(probs.argmax())]  # bool + best match

def clip_match_title(image: Image.Image, title: str):
    """Проверяем соответствие названия и содержимого."""
    inputs = clip.tokenize([title]).to(device)
    image_tensor = PREPROCESS(image).unsqueeze(0).to(device)

    with torch.no_grad():
        logits_per_image, _ = MODEL(image_tensor, inputs)
        probs = logits_per_image.softmax(dim=-1).cpu().numpy()[0][0]

    return probs > 0.25  # порог соответствия
