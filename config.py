from __future__ import annotations

import base64
import json
import os
import uuid
from pathlib import Path


# SciPlan intentionally uses its own data directory so a fresh package starts
# cleanly without importing the earlier ResearchFlow prototype database.
APP_DIR = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "SciPlan"
APP_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = APP_DIR / "config.json"
DB_PATH = APP_DIR / "data.db"

DEFAULT_CONFIG = {
    "base_url": "https://api.deepseek.com",
    "api_key": "",
    "model": "deepseek-chat",
    "allow_review_ai": False,
    "start_on_boot": False,
    "minimize_to_tray": True,
    "providers": [],
    "active_provider_id": "",
    "assistant_user_name": "",
    "assistant_tone": "温和、直接、像熟悉你的科研同事",
    "assistant_memory": "",
    "pet_size": 92,
    "pet_image": "/assets/assistant_character.png",
}


def _decode(value: str) -> str:
    try:
        decoded = base64.b64decode(value.encode()).decode()
        if decoded.startswith("rf:"):
            return decoded[3:]
    except Exception:
        pass
    return value


def _encode(value: str) -> str:
    return base64.b64encode(("rf:" + value).encode()).decode() if value else ""


def load_config() -> dict:
    data = dict(DEFAULT_CONFIG)
    try:
        if CONFIG_PATH.exists():
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            data.update(raw)
            data["api_key"] = _decode(str(data.get("api_key", "")))
            data["providers"] = [{**p, "api_key": _decode(str(p.get("api_key", "")))} for p in (data.get("providers", []) or [])]
    except Exception:
        pass
    if not data["providers"] and (data.get("base_url") or data.get("api_key") or data.get("model")):
        provider_id = str(uuid.uuid4())
        data["providers"] = [{"id": provider_id, "name": "DeepSeek", "base_url": data.get("base_url", "https://api.deepseek.com"), "model": data.get("model", "deepseek-chat"), "api_key": data.get("api_key", ""), "enabled": bool(data.get("api_key")), "last_test": "", "latency_ms": None}]
        data["active_provider_id"] = provider_id if data.get("api_key") else ""
    active = next((p for p in data["providers"] if p.get("id") == data.get("active_provider_id")), None)
    if active:
        data.update({k: active.get(k, data.get(k)) for k in ("base_url", "model", "api_key")})
    return data


def save_config(values: dict) -> dict:
    current = load_config()
    data = dict(DEFAULT_CONFIG); data.update(current)
    data.update({k: values[k] for k in DEFAULT_CONFIG if k in values and k not in ("providers", "api_key", "base_url", "model")})
    if "providers" in values:
        existing = {p.get("id"): p for p in current.get("providers", [])}
        providers = []
        for item in values.get("providers") or []:
            p = dict(item); old = existing.get(p.get("id"), {})
            if (not p.get("api_key") or isinstance(p.get("api_key"), bool)) and old.get("api_key"): p["api_key"] = old["api_key"]
            elif isinstance(p.get("api_key"), bool): p["api_key"] = ""
            p["id"] = p.get("id") or str(uuid.uuid4()); providers.append(p)
        data["providers"] = providers
    else:
        providers = list(current.get("providers", [])); active_id = current.get("active_provider_id") or (providers[0].get("id") if providers else str(uuid.uuid4()))
        provider = next((p for p in providers if p.get("id") == active_id), None)
        if provider is None: provider = {"id": active_id, "name": "DeepSeek"}; providers.append(provider)
        provider.update({"base_url": values.get("base_url", current.get("base_url")), "model": values.get("model", current.get("model"))})
        if values.get("api_key"): provider["api_key"] = values["api_key"]
        provider.setdefault("api_key", current.get("api_key", "")); data["providers"] = providers; data["active_provider_id"] = active_id
    data["active_provider_id"] = values.get("active_provider_id", data.get("active_provider_id", ""))
    active = next((p for p in data["providers"] if p.get("id") == data["active_provider_id"]), None)
    if active: data["base_url"], data["model"], data["api_key"] = active.get("base_url", ""), active.get("model", ""), active.get("api_key", "")
    stored = dict(data); stored["api_key"] = _encode(str(data.get("api_key", ""))); stored["providers"] = []
    for p in data.get("providers", []):
        item = dict(p); item["api_key"] = _encode(str(item.get("api_key", ""))); stored["providers"].append(item)
    CONFIG_PATH.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
    return data
