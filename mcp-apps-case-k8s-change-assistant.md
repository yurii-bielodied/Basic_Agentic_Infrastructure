# Kubernetes Change Assistant as an MCP App

## 1. Мета

Власний **MCP Apps** кейс: інтерактивний помічник для підготовки безпечної зміни в Kubernetes. Замість довгого листування в чаті користувач відкриває UI прямо всередині MCP-хоста, бачить поточний стан deployment, список pod'ів, останні події, заповнює параметри зміни та отримує короткий AI-summary ризиків перед підтвердженням.

Обраний кейс свідомо зроблено **вузьким, але живим**: він не намагається покрити весь lifecycle deployment, а демонструє одну завершену взаємодію, яка добре підходить для MVP і для захисту.

---

## 2. Чому саме цей кейс

### Бізнесова причина

У реальних платформах багато помилок виникає не через відсутність automation, а через неповні або неструктуровані change request: неправильний namespace, не той image tag, відсутність rollback-плану, нерозуміння поточного стану deployment перед зміною.

### Технічна причина

Цей кейс природно демонструє сильні сторони **MCP Apps**:

- **UI всередині хоста**, а не лише текстова відповідь;
- **tool + UI resource** як базовий патерн;
- можливість будувати **multi-step workflow**;
- можливість під'єднати **Sampling** для risk summary;
- можливість під'єднати **Elicitation** для добору відсутніх параметрів.

---

## 3. Опис кейсу

### Назва

**Kubernetes Change Assistant**

### Призначення

Підготувати безпечну зміну для Kubernetes deployment у режимі **dry-run**.

### Що робить користувач

Користувач пише, наприклад:

> Підготуй оновлення deployment `payments-api` у namespace `prod` до image tag `1.9.4`.

### Що робить система

1. Викликається tool `open_change_assistant`.
2. Хост відкриває MCP App UI.
3. UI показує поточний стан deployment:
   - image;
   - replicas;
   - rollout status;
   - pod list;
   - recent events.
4. Користувач заповнює або уточнює параметри зміни.
5. Сервер готує короткий summary:
   - що саме зміниться;
   - які є ризики;
   - що перевірити після rollout.
6. Користувач бачить результат у форматі **dry-run preview**.

---

## 4. Чому це MCP Apps, а не просто tool

Звичайний MCP tool добре підходить для короткої текстової або структурованої відповіді. Але в цьому кейсі є кілька елементів, які зручніше показувати саме як app:

- одночасний перегляд кількох блоків даних;
- форма з залежними параметрами;
- оновлення стану без повторного пояснення в чаті;
- покроковий flow: відкриття → перевірка → уточнення → summary → dry-run.

Тому тут логічно використати MCP Apps як **інтерактивний UI поверх MCP tools**.

---

## 5. Архітектура рішення

## Компоненти

### 5.1 MCP Server

Сервер реєструє:

- `open_change_assistant` — tool, який відкриває UI;
- `get_deployment_status` — повертає стан deployment;
- `get_pod_list` — повертає список pod'ів;
- `get_recent_events` — повертає останні події;
- `prepare_change_summary` — готує підсумок dry-run.

### 5.2 UI Resource

Окремий `ui://` resource віддає HTML-інтерфейс MCP App.

### 5.3 App UI

UI працює всередині sandboxed iframe і викликає серверні tools через host.

### 5.4 Kubernetes layer

У production-версії tools могли б звертатися до Kubernetes API або до внутрішнього backend. Для MVP дозволено використати mock data або спрощений adapter, щоб зосередитися саме на MCP Apps механіці.

---

## 6. Потік взаємодії

### Крок 1. Відкриття app

Користувач викликає кейс через chat prompt.

Tool `open_change_assistant` повертає результат і посилається на `_meta.ui.resourceUri`.

### Крок 2. Рендер UI

Хост читає `ui://` resource і рендерить HTML у sandboxed iframe.

### Крок 3. Завантаження поточного стану

UI одразу викликає tools:

- `get_deployment_status`
- `get_pod_list`
- `get_recent_events`

і показує їх на екрані.

### Крок 4. Введення параметрів зміни

Користувач вводить:

- namespace;
- deployment;
- current image;
- target image tag;
- desired replicas;
- change reason.

### Крок 5. Підготовка summary

UI викликає `prepare_change_summary`, а сервер формує:

- human-readable summary;
- перелік ризиків;
- список перевірок після rollout.

### Крок 6. Dry-run результат

UI показує фінальну картку з підсумком зміни без реального застосування до кластера.

---

## 7. Де тут Sampling, Elicitation та MCP Apps

## MCP Apps

Основна реалізація в цьому кейсі — саме **MCP App**:

- tool відкриває UI;
- UI resource віддається через `ui://`;
- app працює прямо в розмові;
- UI може повторно викликати серверні tools.

## Sampling

У розширеній версії `prepare_change_summary` може не лише повертати шаблонний текст, а й запускати **Sampling**, щоб клієнтова модель згенерувала:

- стислий опис зміни;
- ризики;
- рекомендації після rollout.

Таким чином сервер не зберігає власний LLM API key, а використовує модель через MCP client.

## Elicitation

У розширеній версії, якщо користувач не вказав критичні поля, сервер може запросити їх через **Elicitation**, наприклад:

- maintenance window;
- rollback preference;
- approval reason.

Це дозволяє збирати missing fields у структурованому вигляді, а не через довгу серію уточнюючих повідомлень.

---

## 8. MVP-обсяг

Для сертифікатного завдання достатньо такого MVP:

- один MCP App;
- один основний сценарій;
- 4–5 tools;
- один HTML UI;
- dry-run only;
- без реального rollout у кластер.

### Мінімальний набір функцій

- відкрити app;
- показати mock або live deployment status;
- показати pod list;
- показати recent events;
- зібрати target image tag;
- побудувати summary змін;
- показати dry-run preview.

---

## 9. Пропонована структура проєкту

```text
k8s-change-assistant/
├── package.json
├── main.ts
├── server.ts
├── mcp-app.html
├── src/
│   └── mcp-app.ts
├── dist/
└── README.md
```

### Призначення файлів

- `main.ts` — запуск MCP server;
- `server.ts` — реєстрація tools та UI resource;
- `mcp-app.html` — HTML-шаблон app;
- `src/mcp-app.ts` — логіка UI, виклики tools, рендер результатів;
- `README.md` — опис кейсу, запуск і demo flow.

---

## 10. Приклад tool set

### `open_change_assistant`

Відкриває MCP App.

### `get_deployment_status`

Повертає:

- deployment name;
- namespace;
- current image;
- replicas;
- available replicas;
- rollout condition.

### `get_pod_list`

Повертає список pod'ів із базовим статусом.

### `get_recent_events`

Повертає останні події deployment або namespace.

### `prepare_change_summary`

На вході приймає:

- deployment;
- namespace;
- current image;
- target image;
- replicas;
- change reason.

На виході повертає:

- summary;
- risks;
- checks_after_rollout;
- mode = `dry-run`.

---

## 11. Приклад демо-сценарію

### Сценарій

Користувач хоче підготувати зміну для `payments-api`.

### Демонстрація

1. Користувач просить підготувати оновлення.
2. Відкривається MCP App.
3. UI показує поточний image: `payments-api:1.9.3`.
4. UI показує 3 running pods і останні events.
5. Користувач вводить target image: `payments-api:1.9.4`.
6. Сервер повертає dry-run summary, наприклад:
   - буде оновлено image з `1.9.3` на `1.9.4`;
   - replicas залишаються 3;
   - критичних подій не виявлено;
   - рекомендовано перевірити readiness і HTTP 5xx після rollout.
7. Користувач бачить зрозумілий підсумок зміни без реального застосування.

---

## 12. Чому цей кейс хороший для захисту

Цей кейс хороший для захисту з чотирьох причин:

1. **Реалістичність** — сценарій схожий на справжню platform/devops задачу.
2. **Компактність** — він достатньо вузький для MVP.
3. **Візуальна переконливість** — app виглядає як жива інтерактивна система, а не просто текстовий tool.
4. **Розширюваність** — у майбутньому сюди легко додати live Kubernetes API, Sampling, Elicitation, approval flow, rollback wizard.

---

## 13. Обмеження MVP

У поточному MVP свідомо вводяться обмеження:

- немає реального rollout;
- немає запису змін у кластер;
- можливо використовується mock data;
- Sampling та Elicitation можуть бути позначені як наступний етап, якщо хост/клієнт для демо не підтримує їх повністю.

Це нормальне технічне спрощення для сертифікатної роботи, тому що головна мета — продемонструвати **архітектуру MCP Apps** і живий сценарій взаємодії.

---

## 14. Можливі наступні кроки

Після MVP кейс можна розширити:

- підключити реальний Kubernetes API;
- додати live status refresh;
- додати Sampling для risk analysis;
- додати Elicitation для missing fields;
- додати approve / reject flow;
- додати rollback preview;
- додати audit trail.

---

## 15. Висновок

**Kubernetes Change Assistant** — це хороший приклад власного MCP Apps кейсу для частини **«Досвідчені»**, тому що він одночасно:

- практичний;
- зрозумілий для захисту;
- візуально переконливий;
- побудований на офіційному MCP Apps патерні;
- легко масштабується до повнішого platform workflow.

У межах сертифікатного завдання достатньо реалізувати **dry-run MVP** з одним app, кількома tools і простим UI. Це вже буде повноцінний приклад того, як MCP Apps можуть покращити platform engineering workflow у порівнянні зі звичайним текстовим tool.

---

## 16. Джерела

- MCP Apps overview: https://modelcontextprotocol.io/extensions/apps/overview
- MCP Apps build guide: https://modelcontextprotocol.io/extensions/apps/build
- MCP Apps announcement: https://blog.modelcontextprotocol.io/posts/2026-01-26-mcp-apps/
- MCP Apps SEP-1865: https://modelcontextprotocol.io/seps/1865-mcp-apps-interactive-user-interfaces-for-mcp
- Sampling: https://modelcontextprotocol.io/specification/2025-11-25/client/sampling
- Elicitation: https://modelcontextprotocol.io/specification/2025-06-18/client/elicitation
- Tools: https://modelcontextprotocol.io/specification/2025-11-25/server/tools
- MCP clients page: https://modelcontextprotocol.io/clients
