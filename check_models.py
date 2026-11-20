"""Проверка бесплатных моделей OpenRouter с ключом из .env.

    python check_models.py --list            # только список бесплатных моделей
    python check_models.py                   # проверить модели из MODELS в .env (или список по умолчанию)
    python check_models.py model/a:free ...  # проверить конкретные модели

Ключ берётся из .env и никуда не выводится. Каждая проверка — это один запрос
к модели, а у бесплатного тарифа OpenRouter есть дневной лимит запросов.
"""

import os
import sys
import time

import httpx
from dotenv import load_dotenv

load_dotenv()
KEY = os.getenv("OPENROUTER_API_KEY", "")
BASE = "https://openrouter.ai/api/v1"
HEADERS = {"Authorization": f"Bearer {KEY}", "X-Title": "qaz.su cafe bot"}
DEFAULT_MODELS = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "baidu/ernie-5.5-flash-preview:free",
    "nvidia/nemotron-3.5-super-vl:free",
    "google/gemma-4-31b-it:free",
]


def key_info() -> None:
    r = httpx.get(f"{BASE}/key", headers=HEADERS, timeout=20)
    if r.status_code != 200:
        print(f"key: HTTP {r.status_code}")
        return
    d = r.json().get("data", {})
    print(
        "key: ok | free_tier={} | limit={} | usage={} | rate_limit={}".format(
            d.get("is_free_tier"), d.get("limit"), d.get("usage"), d.get("rate_limit")
        )
    )


def free_models() -> list[str]:
    r = httpx.get(f"{BASE}/models", timeout=30)
    r.raise_for_status()
    out = []
    for m in r.json()["data"]:
        arch = m.get("architecture", {})
        if m["id"].endswith(":free") and "text" in arch.get("output_modalities", ["text"]):
            out.append((m["id"], m.get("context_length")))
    for mid, ctx in sorted(out):
        print(f"{mid}  ctx={ctx}")
    return [mid for mid, _ in out]


def probe(model: str) -> None:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Отвечай одним коротким предложением по-русски."},
            {"role": "user", "content": "Сколько будет 2+2?"},
        ],
        "max_tokens": 300,
        # у "думающих" моделей без этого весь лимит токенов уходит на рассуждения
        "reasoning": {"enabled": False, "exclude": True},
    }
    t = time.time()
    try:
        r = httpx.post(f"{BASE}/chat/completions", headers=HEADERS, json=body, timeout=60)
    except httpx.HTTPError as e:
        print(f"FAIL  {model}: {type(e).__name__}")
        return
    dt = time.time() - t
    if r.status_code != 200:
        err = r.json().get("error", {}).get("message", r.text)[:120] if r.content else ""
        print(f"FAIL  {model}: HTTP {r.status_code} {err}")
        return
    data = r.json()
    if "error" in data:
        print(f"FAIL  {model}: {str(data['error'].get('message'))[:120]}")
        return
    text = (data["choices"][0]["message"].get("content") or "").strip().replace("\n", " ")
    status = "OK   " if text else "EMPTY"
    print(f"{status} {model}  {dt:.1f}s  -> {text[:80]}")


if __name__ == "__main__":
    if not KEY:
        sys.exit("OPENROUTER_API_KEY не найден в .env")
    key_info()
    args = sys.argv[1:]
    if args == ["--list"]:
        free_models()
        sys.exit()
    models = args or [m.strip() for m in os.getenv("MODELS", "").split(",") if m.strip()] or DEFAULT_MODELS
    for m in models:
        probe(m)
