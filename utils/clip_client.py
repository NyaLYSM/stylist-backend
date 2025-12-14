# utils/clip_client.py
import requests

CLIP_URL = "http://127.0.0.1:8001"

def clip_check_clothing(image_url: str) -> dict:
    try:
        r = requests.post(
            f"{CLIP_URL}/check-clothing",
            json={"image_url": image_url},
            timeout=15
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {
            "ok": False,
            "error": str(e)
        }
