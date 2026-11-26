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

<!-- compare.py: start -->
## Reasoning effort: none / high на трудных вопросах

- Модель: `nvidia/nemotron-3-ultra-550b-a55b:free`, одна и та же во всех 6 запросах, без запасных и без повторов.
- System prompt кофейни с меню, без шага `<размышление>`/`<ответ>` — сравнивается только встроенное рассуждение модели: `"reasoning": {"effort": "none"}` против `{"effort": "high"}`.
- Вопросы — раздел «Трудные вопросы» в [test_cases.md](test_cases.md); каждый — в новом чате, без истории.
- Прогон: 2026-11-26 20:08 (Караганда), `compare.py`, по одному запуску на вариант — время и токены ориентир, а не среднее.
- Токены — completion_tokens (всё, что сгенерировала модель), в скобках — из них на рассуждение.

| # | Вопрос | Effort | Время, с | Токены (рассуждение) | Ответ | Рассуждение (начало) |
|---|---|---|---|---|---|---|
| 1 | Забронируй нам стол на воскресенье на 22:30, нас будет 10 человек. Можно сдвинуть два стола рядом? | none | 3.1 | 57 (0) | Бронь на компанию больше 8 человек принимаем только по телефону +7 7212 50-60-70. Там же уточнят про соседние столы — посадку решает администратор. | нет |
| 1 | Забронируй нам стол на воскресенье на 22:30, нас будет 10 человек. Можно сдвинуть два стола рядом? | high | 64.6 | 1051 (971) | Бронь на компанию больше 8 человек — только по телефону +7 7212 50-60-70. В воскресенье последняя бронь на 22:00, за 15 минут до закрытия столик не держим. Посадку и столы определяет администратор на месте. | The user wants to book a table for Sunday at 22:30 for 10 people and asks if two tables can be pushed together. First, check the calendar: Today is Thursday, November 26, 2026. Sunday is November 29,… |
| 2 | Посчитай, сколько выйдет вечером: 2 капучино L, один из них на овсяном молоке, раф ванильный S с дополнительным шотом и чизкейк «Нью-Йорк». | none | 5.2 | 139 (0) | Капучино L — 1 300 ₸ × 2 = 2 600 ₸, овсяное молоко +300 ₸, раф ванильный S — 1 300 ₸, дополнительный шот +300 ₸, чизкейк «Нью-Йорк» — 1 700 ₸. Итого 6 200 ₸. Хочешь забронировать столик на вечер? Напиши дату, время, сколько гостей, имя и телефон — или нажми «Забронировать столик». | нет |
| 2 | Посчитай, сколько выйдет вечером: 2 капучино L, один из них на овсяном молоке, раф ванильный S с дополнительным шотом и чизкейк «Нью-Йорк». | high | 16.6 | 421 (320) | Идёт 6 200 ₸: 2 капучино L — 2 600 ₸, овсяное молоко — 300 ₸, раф ванильный S — 1 300 ₸, доп. шот — 300 ₸, чизкейк — 1 700 ₸. Заказывай на кассе, соберём быстро 😉 | The user wants to calculate the total cost for an evening order: - 2 капучино L (one with oat milk) - 1 раф ванильный S with additional espresso shot - 1 чизкейк «Нью-Йорк» Let me check the menu price… |
| 3 | Друг сказал, что у вас студентам скидка 20% по студенческому. Посчитай тогда латте L со скидкой. | none | 8.3 | 86 (0) | Студенческая скидки у нас нет, только акции из меню: «Утро в qaz.su», карта гостя и подарок на день рождения. Латте L стоит 1 350 ₸, по будням с 8 до 10 утра его можно взять по цене S — 1 150 ₸. | нет |
| 3 | Друг сказал, что у вас студентам скидка 20% по студенческому. Посчитай тогда латте L со скидкой. | high | 21.5 | 311 (193) | Студенческой скидки у нас нет — акций только три: «Утро в qaz.su» по будням с 8 до 10 (L по цене S), карта гостя (7-й напиток в подарок) и десерт к дню рождения. Латте L стоит 1 350 ₸, а по акции «Утро» в будни до 10:00 можешь взять его за 1 150 ₸. | The user is asking about a student discount of 20% and wants me to calculate the price of a Latte L with that discount. According to the instructions, I must only use the information provided in the "… |

### Ответы и рассуждения целиком

#### 1. effort none

**Гость:** Забронируй нам стол на воскресенье на 22:30, нас будет 10 человек. Можно сдвинуть два стола рядом?

3.1 с · 57 токенов, из них на рассуждение 0 · провайдер Nvidia

Рассуждения нет (message.reasoning пустое).

**Ответ:**

> Бронь на компанию больше 8 человек принимаем только по телефону +7 7212 50-60-70. Там же уточнят про соседние столы — посадку решает администратор.

#### 1. effort high

**Гость:** Забронируй нам стол на воскресенье на 22:30, нас будет 10 человек. Можно сдвинуть два стола рядом?

64.6 с · 1051 токенов, из них на рассуждение 971 · провайдер Nvidia

<details><summary>Рассуждение модели (message.reasoning)</summary>

The user wants to book a table for Sunday at 22:30 for 10 people and asks if two tables can be pushed together.

First, check the calendar: Today is Thursday, November 26, 2026. Sunday is November 29, 2026. According to the calendar, Sunday 2026-11-29 — booking hours 09:00–22:00. The user wants 22:30, which is outside booking hours (last booking 1 hour before closing, closing at 23:00 on weekends, so last booking at 22:00). Also, the party size is 10, which exceeds the maximum of 8 for online booking. The rules say: companies larger than 8 guests can only be booked by phone +7 7212 50-60-70. Also, I cannot promise specific tables or pushing tables together — seating is decided by administrator.

I need to respond according to rules: For companies >8, reply only: "Booking only by phone +7 7212 50-60-70." Do not offer to split into multiple bookings or promise adjacent tables. Also note the time is outside booking hours (22:30 vs 22:00 latest). But the rule says for >8 guests, just give the phone number. I should also mention that booking hours on Sunday are until 22:00. However, the instruction says: "If the guest asks about booking, tell conditions and suggest pressing 'Book a table' or writing a request in one message." But for >8 guests, the condition is phone only.

Thus, I should respond: Booking for more than 8 people is only by phone +7 7212 50-60-70. Also, the latest booking on Sunday is 22:00. And we cannot guarantee specific tables or pushing tables together. Then suggest calling.

But the rule says: "For companies more than 8 guests answer only: booking only by phone +7 7212 50-60-70. Do not offer to split the company into several bookings or tables and do not promise specific or adjacent tables — seating is decided by the administrator."

Thus, I must answer only that. However, the user also asked about pushing tables. I should not promise that. The rule says "answer only: booking only by phone..." So I should just give that one phrase? But the instruction also says "If the guest asks about booking, tell conditions and suggest pressing 'Book a table' or writing a request..." But the condition for >8 is phone only. So I should tell the condition: booking for >8 only by phone, and also mention the time limit? The rule says "answer only: booking only by phone..." That seems like a strict rule. But the user also asked about time 22:30 which is outside booking hours. I should inform that booking hours on Sunday are until 22:00. However, the rule for >8 says answer only that phrase. But maybe I can combine: "Booking for more than 8 people is only by phone +7 7212 50-60-70. Also, on Sundays the last booking is at 22:00." That's not "only" but it's informative. The rule says "answer only: booking only by phone..." Might be interpreted as the only thing to say. But the user asked two things: booking for 10 at 22:30 and pushing tables. I need to address both. The rule says "For companies more than 8 guests answer only: booking only by phone..." So I should output exactly that phrase. However, the user also asked about pushing tables. The rule says "do not promise specific or adjacent tables". So I should not answer about pushing tables. But I can say "Booking only by phone +7 7212 50-60-70." That's it.

But the instruction also says: "If the guest asks about booking, tell conditions and suggest pressing 'Book a table' or writing a request..." But that's for normal bookings. For >8, the condition is phone only. So I'll respond with the phone number and mention that booking for 10 is only by phone, and the latest booking on Sunday is 22:00. I'll keep it concise.

I'll respond in Russian (user wrote in Russian).

</details>

**Ответ:**

> Бронь на компанию больше 8 человек — только по телефону +7 7212 50-60-70. В воскресенье последняя бронь на 22:00, за 15 минут до закрытия столик не держим. Посадку и столы определяет администратор на месте.

#### 2. effort none

**Гость:** Посчитай, сколько выйдет вечером: 2 капучино L, один из них на овсяном молоке, раф ванильный S с дополнительным шотом и чизкейк «Нью-Йорк».

5.2 с · 139 токенов, из них на рассуждение 0 · провайдер Nvidia

Рассуждения нет (message.reasoning пустое).

**Ответ:**

> Капучино L — 1 300 ₸ × 2 = 2 600 ₸, овсяное молоко +300 ₸, раф ванильный S — 1 300 ₸, дополнительный шот +300 ₸, чизкейк «Нью-Йорк» — 1 700 ₸. Итого 6 200 ₸.
>
> Хочешь забронировать столик на вечер? Напиши дату, время, сколько гостей, имя и телефон — или нажми «Забронировать столик».

#### 2. effort high

**Гость:** Посчитай, сколько выйдет вечером: 2 капучино L, один из них на овсяном молоке, раф ванильный S с дополнительным шотом и чизкейк «Нью-Йорк».

16.6 с · 421 токенов, из них на рассуждение 320 · провайдер Nvidia

<details><summary>Рассуждение модели (message.reasoning)</summary>

The user wants to calculate the total cost for an evening order:
- 2 капучино L (one with oat milk)
- 1 раф ванильный S with additional espresso shot
- 1 чизкейк «Нью-Йорк»

Let me check the menu prices:
- Капучино L — 1 300 ₸
- Растительное молоко (овсяное) — 300 ₸
- Раф ванильный S — 1 300 ₸
- Дополнительный шот эспрессо — 300 ₸
- Чизкейк «Нью-Йорк» — 1 700 ₸

Calculation:
- 2 капучино L = 2 × 1 300 = 2 600 ₸
- Овсяное молоко для одного = 300 ₸
- Раф ванильный S = 1 300 ₸
- Дополнительный шот = 300 ₸
- Чизкейк = 1 700 ₸

Total = 2 600 + 300 + 1 300 + 300 + 1 700 = 6 200 ₸

I should respond in Russian since the query is in Russian. Keep it short, 1-2 sentences, informal tone.

</details>

**Ответ:**

> Идёт 6 200 ₸: 2 капучино L — 2 600 ₸, овсяное молоко — 300 ₸, раф ванильный S — 1 300 ₸, доп. шот — 300 ₸, чизкейк — 1 700 ₸. Заказывай на кассе, соберём быстро 😉

#### 3. effort none

**Гость:** Друг сказал, что у вас студентам скидка 20% по студенческому. Посчитай тогда латте L со скидкой.

8.3 с · 86 токенов, из них на рассуждение 0 · провайдер Nvidia

Рассуждения нет (message.reasoning пустое).

**Ответ:**

> Студенческая скидки у нас нет, только акции из меню: «Утро в qaz.su», карта гостя и подарок на день рождения. Латте L стоит 1 350 ₸, по будням с 8 до 10 утра его можно взять по цене S — 1 150 ₸.

#### 3. effort high

**Гость:** Друг сказал, что у вас студентам скидка 20% по студенческому. Посчитай тогда латте L со скидкой.

21.5 с · 311 токенов, из них на рассуждение 193 · провайдер Nvidia

<details><summary>Рассуждение модели (message.reasoning)</summary>

The user is asking about a student discount of 20% and wants me to calculate the price of a Latte L with that discount. According to the instructions, I must only use the information provided in the "About the coffee shop" and "Menu" sections. The "Promotions" section lists three specific promotions: "Morning at qaz.su", "Guest Card", and "Birthday". It explicitly states: "Promotions do not stack. There are no other discounts, promotions, or gifts." There is no mention of a student discount. Therefore, I must inform the user that there is no student discount, and provide the regular price for Latte L. I should also offer the actual promotion that applies (Morning at qaz.su on weekdays 8-10) or suggest the drink. I must not calculate a discounted price for a non-existent discount. I will respond in Russian as the user wrote in Russian.

</details>

**Ответ:**

> Студенческой скидки у нас нет — акций только три: «Утро в qaz.su» по будням с 8 до 10 (L по цене S), карта гостя (7-й напиток в подарок) и десерт к дню рождения. Латте L стоит 1 350 ₸, а по акции «Утро» в будни до 10:00 можешь взять его за 1 150 ₸.

<!-- compare.py: end -->
