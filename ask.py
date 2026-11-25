"""Ручное сравнение: одна и та же модель с рассуждением и без.

    .venv\\Scripts\\python.exe ask.py on  "вопрос"   # reasoning включён
    .venv\\Scripts\\python.exe ask.py off "вопрос"   # reasoning выключен

Один запрос к OpenRouter с system prompt кофейни и меню, но без шага <размышление>/<ответ>:
сравниваем только встроенный reasoning модели. Печатает время ответа и ответ,
дописывает результат в comparison_raw.md. Ключ берётся из .env и никуда не выводится.
"""

import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

from cafe import TZ, load_prompt_template, now_block

BASE_DIR = Path(__file__).resolve().parent
OUT = BASE_DIR / "comparison_raw.md"

# Шаг рассуждения из system_prompt.md: раздел целиком и фраза про него в блоке <примеры>
REASONING_SECTION_RE = re.compile(r"## Рассуждение перед ответом\n.*?(?=\n## )", re.S)
REASONING_NOTE = " В примерах показан только текст из <ответ>, а размышление пиши всегда."


def cafe_prompt_without_reasoning() -> str:
    prompt = load_prompt_template().replace("{{NOW}}", now_block(datetime.now(TZ)))
    if not REASONING_SECTION_RE.search(prompt):
        sys.exit("В system_prompt.md не найден раздел «## Рассуждение перед ответом»")
    prompt = REASONING_SECTION_RE.sub("", prompt).replace(REASONING_NOTE, "")
    if "<ответ>" in prompt or "<размышление>" in prompt:
        sys.exit("В system prompt остались теги <размышление>/<ответ> — проверь вырезание в ask.py")
    return prompt

# Бесплатная модель с параметром reasoning (supported_parameters в GET /api/v1/models, проверено 26.11.2026)
MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
MAX_TOKENS = 8000  # с запасом: рассуждение тоже тратит токены и не должно съесть ответ
TIMEOUT = 180


def ask(mode: str, question: str) -> None:
    load_dotenv(BASE_DIR / ".env")
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        sys.exit("OPENROUTER_API_KEY не найден в .env")

    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": cafe_prompt_without_reasoning()},
            {"role": "user", "content": question},
        ],
        "max_tokens": MAX_TOKENS,
        "reasoning": {"enabled": mode == "on"},
    }
    started = time.monotonic()
    r = httpx.post("https://openrouter.ai/api/v1/chat/completions", json=body, timeout=TIMEOUT,
                   headers={"Authorization": f"Bearer {key}", "X-Title": "qaz.su cafe bot"})
    elapsed = time.monotonic() - started

    if r.status_code != 200:
        sys.exit(f"HTTP {r.status_code}: {r.text[:300]}")
    data = r.json()
    if data.get("error"):
        sys.exit(f"Ошибка провайдера: {str(data['error'].get('message'))[:300]}")
    msg = (data.get("choices") or [{}])[0].get("message") or {}
    answer = (msg.get("content") or "").strip() or "(пустой ответ)"
    reasoning = (msg.get("reasoning") or "").strip()
    usage = data.get("usage") or {}
    r_tokens = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
    tokens = f"токенов ответа: {usage.get('completion_tokens', '?')}" + (
        f", из них на рассуждение: {r_tokens}" if r_tokens else "")

    print(f"reasoning {mode} · {MODEL} · {elapsed:.1f} с · {tokens}\n")
    print(answer)

    entry = [
        f"## {datetime.now(TZ):%Y-%m-%d %H:%M} · reasoning {mode}",
        "",
        f"- Модель: `{MODEL}`",
        "- System prompt: кофейни с меню, без шага `<размышление>`/`<ответ>`",
        f"- Время ответа: {elapsed:.1f} с",
        f"- {tokens[0].upper()}{tokens[1:]}",
        "",
        f"**Вопрос:** {question}",
        "",
    ]
    if reasoning:
        entry += ["<details><summary>Рассуждение модели</summary>", "", reasoning, "", "</details>", ""]
    entry += ["**Ответ:**", "", answer, "", "---", "", ""]
    new = not OUT.exists()
    with OUT.open("a", encoding="utf-8") as f:
        if new:
            f.write("# Сравнение: reasoning on / off\n\nЗаписи добавляет ask.py, по одной на запрос.\n\n")
        f.write("\n".join(entry))
    print(f"\nЗаписано в {OUT.name}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) != 3 or sys.argv[1] not in ("on", "off") or not sys.argv[2].strip():
        sys.exit('Запуск: ask.py on "вопрос"  или  ask.py off "вопрос"')
    ask(sys.argv[1], sys.argv[2].strip())
