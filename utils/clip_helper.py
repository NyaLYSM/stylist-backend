import requests

CLIP_URL = "http://127.0.0.1:8001/check"

def clip_check(image_url: str, title: str) -> bool:
    try:
        r = requests.post(CLIP_URL, json={
            "image_url": image_url,
            "title": title
        }, timeout=5)
        r.raise_for_status()
        data = r.json()
        return data.get("ok", False)
    except Exception:
        return False
