"""Hashing helpers for voice cache."""
import hashlib
import json


def _compute_text_hash(voice_id: str, text: str, settings_dict: dict) -> str:
    """احسب hash فريد للنص + الصوت + الإعدادات."""
    payload = f"{voice_id}|{text}|{json.dumps(settings_dict, sort_keys=True)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
