"""Сравнение reasoning effort: none / high на трёх трудных вопросах из test_cases.md.

    .venv\\Scripts\\python.exe compare.py

Каждый вопрос из раздела «## Трудные вопросы» отправляется в OpenRouter дважды одной и той же
бесплатной модели: reasoning {"effort": "none"} и {"effort": "high"} — всего 6 запросов, без повторов.
System prompt — кофейни с меню, без шага <размышление>/<ответ> (как в ask.py), чтобы сравнивать
только встроенное рассуждение модели. Для каждого запуска пишется ответ, время, токены и текст
из message.reasoning. Итог — раздел в comparison.md между метками START/END (остальное не трогается).
Ключ берётся из .env и никуда не выводится. Бот (cafe.py, bot.py) не меняется.
"""

import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

from ask import cafe_prompt_without_reasoning
from cafe import TZ

BASE_DIR = Path(__file__).resolve().parent
TEST_CASES = BASE_DIR / "test_cases.md"
OUT = BASE_DIR / "comparison.md"
START = "<!-- compare.py: start -->"
END = "<!-- compare.py: end -->"

# Бесплатная модель, у которой рассуждение можно выключить: в GET /api/v1/models (26.11.2026)
# reasoning.mandatory = false, supported_efforts = ["high", "medium", "none"].
MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
EFFORTS = ["none", "high"]
MAX_TOKENS = 8000  # с запасом: рассуждение тоже тратит токены и не должно съесть ответ
TIMEOUT = 180


def hard_questions() -> list[tuple[str, str]]:
    """[(заголовок, вопрос гостя)] из раздела «## Трудные вопросы»."""
    text = TEST_CASES.read_text(encoding="utf-8").replace("\r\n", "\n")
    m = re.search(r"^## Трудные вопросы\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    if not m:
        sys.exit("В test_cases.md нет раздела «## Трудные вопросы»")
    items = re.findall(r"^### \d+\.\s*(.+?)\n.*?^\*\*Гость:\*\*\s*(.+?)$", m.group(1), re.S | re.M)
    if len(items) != 3:
        sys.exit(f"Ожидалось 3 вопроса в «Трудных вопросах», найдено {len(items)}")
    return [(title.strip(), q.strip()) for title, q in items]


def run(client: httpx.Client, system: str, question: str, effort: str) -> dict:
    body = {
        "model": MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": question}],
        "max_tokens": MAX_TOKENS,
        "reasoning": {"effort": effort},
    }
    started = time.monotonic()
    try:
        r = client.post("https://openrouter.ai/api/v1/chat/completions", json=body)
    except httpx.HTTPError as e:
        return {"error": f"{type(e).__name__}: {e}", "elapsed": time.monotonic() - started}
    elapsed = time.monotonic() - started
    if r.status_code != 200:
        return {"error": f"HTTP {r.status_code}: {r.text[:300]}", "elapsed": elapsed}
    data = r.json()
    if data.get("error"):
        return {"error": str(data["error"].get("message"))[:300], "elapsed": elapsed}
    msg = (data.get("choices") or [{}])[0].get("message") or {}
    usage = data.get("usage") or {}
    return {
        "answer": (msg.get("content") or "").strip(),
        "reasoning": (msg.get("reasoning") or "").strip(),
        "elapsed": elapsed,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0,
        "provider": data.get("provider", ""),
    }


def cell(text: str, limit: int | None = None) -> str:
    text = " ".join(text.split())
    if limit and len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text.replace("|", "\\|") or "—"


def render(results: list[tuple[str, str, str, dict]], started: datetime) -> str:
    lines = [
        START,
        "## Reasoning effort: none / high на трудных вопросах",
        "",
        f"- Модель: `{MODEL}`, одна и та же во всех 6 запросах, без запасных и без повторов.",
        "- System prompt кофейни с меню, без шага `<размышление>`/`<ответ>` — сравнивается только встроенное "
        "рассуждение модели: `\"reasoning\": {\"effort\": \"none\"}` против `{\"effort\": \"high\"}`.",
        "- Вопросы — раздел «Трудные вопросы» в [test_cases.md](test_cases.md); каждый — в новом чате, без истории.",
        f"- Прогон: {started:%Y-%m-%d %H:%M} (Караганда), `compare.py`, по одному запуску на вариант — "
        "время и токены ориентир, а не среднее.",
        "- Токены — completion_tokens (всё, что сгенерировала модель), в скобках — из них на рассуждение.",
        "",
        "| # | Вопрос | Effort | Время, с | Токены (рассуждение) | Ответ | Рассуждение (начало) |",
        "|---|---|---|---|---|---|---|",
    ]
    for n, question, effort, r in results:
        if "error" in r:
            lines.append(f"| {n} | {cell(question)} | {effort} | {r['elapsed']:.1f} | — | Ошибка: {cell(r['error'])} | — |")
            continue
        lines.append(
            f"| {n} | {cell(question)} | {effort} | {r['elapsed']:.1f} | "
            f"{r['completion_tokens']} ({r['reasoning_tokens']}) | {cell(r['answer'] or '(пустой ответ)')} | "
            f"{cell(r['reasoning'], 200) if r['reasoning'] else 'нет'} |"
        )
    lines += ["", "### Ответы и рассуждения целиком", ""]
    for n, question, effort, r in results:
        lines += [f"#### {n}. effort {effort}", "", f"**Гость:** {question}", ""]
        if "error" in r:
            lines += [f"Ошибка за {r['elapsed']:.1f} с: {r['error']}", ""]
            continue
        lines += [
            f"{r['elapsed']:.1f} с · {r['completion_tokens']} токенов, из них на рассуждение "
            f"{r['reasoning_tokens']} · провайдер {r['provider'] or '?'}",
            "",
        ]
        if r["reasoning"]:
            lines += ["<details><summary>Рассуждение модели (message.reasoning)</summary>", "",
                      r["reasoning"], "", "</details>", ""]
        else:
            lines += ["Рассуждения нет (message.reasoning пустое).", ""]
        lines += ["**Ответ:**", ""] + [f"> {ln}" if ln else ">" for ln in (r["answer"] or "(пустой ответ)").split("\n")] + [""]
    lines.append(END)
    return "\n".join(lines)


def write(section: str) -> None:
    old = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
    if pattern.search(old):
        new = pattern.sub(lambda _: section, old)
    else:
        new = old.rstrip() + "\n\n" + section + "\n" if old else section + "\n"
    OUT.write_text(new, encoding="utf-8")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv(BASE_DIR / ".env")
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        sys.exit("OPENROUTER_API_KEY не найден в .env")

    questions = hard_questions()
    system = cafe_prompt_without_reasoning()
    started = datetime.now(TZ)
    results = []
    headers = {"Authorization": f"Bearer {key}", "X-Title": "qaz.su cafe bot"}
    with httpx.Client(timeout=TIMEOUT, headers=headers) as client:
        for n, (_title, question) in enumerate(questions, 1):
            for effort in EFFORTS:
                r = run(client, system, question, effort)
                status = r.get("error") or (f"{r['completion_tokens']} ток. "
                                            f"(рассуждение {r['reasoning_tokens']})")
                print(f"{n} · effort {effort} · {r['elapsed']:.1f} с · {status}")
                results.append((n, question, effort, r))

    write(render(results, started))
    print(f"Записано в {OUT.name}")


if __name__ == "__main__":
    main()
