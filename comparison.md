# Сравнение: встроенный reasoning модели — off / on

- Модель: `nvidia/nemotron-3-ultra-550b-a55b:free`, одна и та же во всех запросах.
- System prompt кофейни с меню, без шага `<размышление>`/`<ответ>` — сравнивается только встроенный reasoning модели (`"reasoning": {"enabled": true/false}`).
- Запросы делались вручную через `ask.py` 26.11.2026, 01:09–01:11 (Караганда); по одному запуску на вариант, так что время и токены — ориентир, а не среднее.
- Сырые записи — в [comparison_raw.md](comparison_raw.md).

## Итог

| # | Вопрос | Время off | Время on | Токены off | Токены on (из них рассуждение) | Верно off | Верно on | Вывод |
|---|---|---|---|---|---|---|---|---|
| 1 | Можно прийти компанией 12 человек в субботу в 19:00? | 2.8 с | 8.0 с | 71 | 240 (155) | Да | Да | Оба сказали «только по телефону». On добавил дату и часы субботы — верно (до 23:00, последняя бронь в 22:00), хотя в рассуждении модель спутала окно броней с часами работы. Рассуждение ответ не улучшило, а стоило ×3 по времени. |
| 2 | Сколько выйдет: 2 латте L, медовик и миндальный круассан? | 3.9 с | 9.2 с | 56 | 308 (223) | Да | Да | Итог 5 500 ₸ в обоих. On расписал цены по позициям и добавил следующий шаг, но фраза «столик под эту компанию» лишняя. На простом сложении reasoning не нужен. |
| 3 | Есть безглютеновый торт? Сколько стоит? | 4.8 с | 11.2 с | 143 | 446 (344) | Частично | Частично | Оба честно сказали «нет в меню» с [уточнить], цены верные. Off вывалил 6 позиций, включая круассаны. On короче (2 позиции), в рассуждении сам заметил, что круассан «скорее с глютеном», но всё равно предложил брауни и чак-чак, не предупредив про глютен. |

**Коротко:** на этих трёх вопросах reasoning ни разу не исправил ошибку, которую сделал бы обычный режим. Он сделал ответы чуть аккуратнее по форме, но был в 2,3–2,9 раза медленнее и тратил в 3–5,5 раза больше токенов. Рассуждения модель пишет по-английски, даже на русский вопрос.

## Ответы целиком

### 1. Можно прийти компанией 12 человек в субботу в 19:00?

**Reasoning off** · 2.8 с · 71 токен

> Компанию из 12 человек можем принять только по телефону +7 7212 50-60-70. Там же уточнят посадку и свободные столы. Если соберётесь до 8 человек — бронирую тут одной кнопкой.

**Reasoning on** · 8.0 с · 240 токенов, из них на рассуждение 155

<details><summary>Рассуждение модели</summary>

The user is asking about a reservation for 12 people on Saturday at 19:00. According to the rules, companies larger than 8 people can only be booked by phone. I need to inform them of this and provide the phone number. I should also mention the booking conditions briefly. The current date is Thursday, November 26, 2026. Saturday would be November 28, 2026. The hours for Saturday are 09:00-22:00, with last booking at 21:00. 19:00 is within that window. But the group size is 12 > 8, so phone booking only. I'll respond accordingly.

</details>

> Компанию больше 8 человек можно забронировать только по телефону +7 7212 50-60-70. Там же уточнят свободные столы на субботу 28 ноября к 19:00 (мы работаем до 23:00, последняя бронь — 22:00).

### 2. Сколько выйдет: 2 латте L, медовик и миндальный круассан?

**Reasoning off** · 3.9 с · 56 токенов

> 2 латте L (2 × 1 350 ₸) + медовик 1 500 ₸ + миндальный круассан 1 300 ₸ = 5 500 ₸.

**Reasoning on** · 9.2 с · 308 токенов, из них на рассуждение 223

<details><summary>Рассуждение модели</summary>

The user is asking for the total price of a specific order: 2 Latte L, Medovik (honey cake), and Almond Croissant.
I need to look up the prices in the Menu section.

Menu prices:
- Латте (Latte) L (350 мл) — 1 350 ₸
- Медовик (Medovik) — 1 500 ₸
- Круассан миндальный (Almond Croissant) — 1 300 ₸

Calculation:
2 * Latte L = 2 * 1350 = 2700 ₸
Medovik = 1500 ₸
Almond Croissant = 1300 ₸
Total = 2700 + 1500 + 1300 = 5500 ₸

I should respond in Russian (user language), informally, with the total and individual prices. No markdown. One emoji max.

</details>

> 2 латте L — 2 700 ₸ (1 350 ₸ за штуку), медовик — 1 500 ₸, миндальный круассан — 1 300 ₸. Итого: 5 500 ₸. Хочешь забронировать столик под эту компанию?

### 3. Есть безглютеновый торт? Сколько стоит?

**Reasoning off** · 4.8 с · 143 токена

> Безглютенового торта в меню нет — [уточнить] у бариста или по телефону +7 7212 50-60-70.
>
> Зато есть брауни за 1 100 ₸, чизкейк «Нью-Йорк» за 1 700 ₸, медовик за 1 500 ₸ и чак-чак за 800 ₸. Можно также взять классический круассан за 900 ₸ или миндальный за 1 300 ₸.

**Reasoning on** · 11.2 с · 446 токенов, из них на рассуждение 344

<details><summary>Рассуждение модели</summary>

The user is asking about a gluten-free cake and its price. I need to check the menu for gluten-free options. Looking at the menu section:

Desserts:
- Круассан классический — 900 ₸
- Круассан миндальный — 1 300 ₸
- Чизкейк «Нью-Йорк» — 1 700 ₸
- Медовик — 1 500 ₸
- Брауни — 1 100 ₸
- Чак-чак, порция — 800 ₸

None of these are explicitly labeled as gluten-free. The user is asking specifically for a gluten-free cake. According to rule 2: if an item is not in the menu, say it's not available and suggest a similar item from the menu with its price. Also rule 3: if the answer is not in menu or coffee shop info (like allergens), say I don't have that info, mark [уточнить], and suggest asking barista or phone.

But the question is about existence of gluten-free cake and price. Since it's not in menu, I should say we don't have a gluten-free cake in the menu. Could suggest something else? Maybe the almond croissant? But that likely contains gluten. Better to be honest: no gluten-free cake in menu. Suggest asking barista for allergens. Provide phone.

I'll respond in Russian (user wrote in Russian). Keep it short, 1-2 sentences. No markdown. Use friendly tone. End with next step suggestion.

</details>

> В меню нет безглютенового торта — [уточнить] у бариста или по телефону +7 7212 50-60-70, вдруг появятся новые десерты. А из текущих можно попробовать брауни за 1 100 ₸ или чак-чак за 800 ₸ — без торта, но с удовольствием 😉
