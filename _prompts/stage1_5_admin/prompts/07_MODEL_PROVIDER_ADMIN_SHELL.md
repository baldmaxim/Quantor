# PROMPT 07 — Model Providers: management shell only

Stage 2 будет использовать локальные и удалённые модели. Сейчас подготовь control-plane contracts, но НЕ вызывай модели и НЕ реализуй QTO.

## Model provider concepts

Разделить:

```text
Provider        LM Studio / vLLM / SGLang / OpenAI-compatible / Anthropic-like / custom
Endpoint        deployment/base endpoint
Model           model identifier
Capability      text / vision / embeddings / rerank / structured_output / tool_use
Policy          local-only / remote-allowed / restricted-data
CredentialRef   secret reference, never raw secret response
Health          observed connectivity/capability status
```

Не hardcode конкретного vendor в domain calculations.

## Admin UI

`Model Providers` показывает:

- provider name/type;
- endpoint label;
- enabled;
- local/remote classification;
- capabilities;
- model ids;
- timeout/concurrency policy if safe runtime config;
- credential configured yes/no;
- last health check;
- latency from explicit health probe only;
- no prompts/QTO yet.

## Secrets

Stage 1.5 не обязана строить Vault. Если secrets сейчас только env — хранить `CredentialRef`/status and document rotation path. Не класть API keys в general settings DB.

## Provider-neutral contracts

Используй/расширь существующий `apps/api/app/contracts/models.py` из Stage 1 handoff.

Нужны interfaces/DTOs, а не SDK integrations.

## Future compatibility

Контракт должен позволить позже подключить:

- local vLLM/SGLang/LM Studio;
- OpenAI-compatible APIs;
- multimodal VLM;
- fine-tuned Unsloth checkpoints served behind compatible endpoint;
- cloud models;
- per-task routing.

Не реализовывать router/agent orchestration сейчас.

## Tests

- secrets masked;
- invalid capability config rejected;
- only admin can manage;
- health probe failure isolated;
- provider disabled state reflected;
- no model call made in ordinary admin page load.

STOP.
