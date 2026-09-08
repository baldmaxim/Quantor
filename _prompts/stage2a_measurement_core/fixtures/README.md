# Fixtures Stage 2A

Большие пользовательские PDF/ZIP в этот пакет не включены.

Для live-acceptance Claude должен искать fixture в таком порядке:

1. путь из `QTO_LIVE_FIXTURE`;
2. `_prompts/stage2a_measurement_core/fixtures/live/`;
3. уже существующий Stage 1 live fixture в репозитории;
4. если ничего нет — не выдумывать результат, отметить live gate BLOCKED и выполнить synthetic tests.

Предпочтительный эталон — уже использованный пакет
`01-03-00-01-12_ПД-00260560-АР.zip` (77 листов / 383 regions), если он доступен локально.
