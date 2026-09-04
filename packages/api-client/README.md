# @quantor/api-client

Сгенерированный TypeScript-клиент Quantor API.

**Файлы в `src/` и `openapi.json` править руками нельзя** — они перезаписываются генератором.
Источник правды — схемы FastAPI в `apps/api`.

```bash
pnpm api-client:generate   # FastAPI -> openapi.json -> src/
pnpm api-client:check      # то же + проверка, что в git нет расхождений
```

Если CI падает на `api-client:check`, значит контракт API поменялся, а сгенерированный
клиент не закоммичен: выполните `pnpm api-client:generate` и добавьте изменения в коммит.
