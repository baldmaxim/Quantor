# PROMPT 06 — Private PlanSwift dataset importer

Создай **offline/private** importer, не production API endpoint.

## Storage boundary

- raw PlanSwift archives/extracted contents never committed;
- dataset root задаётся CLI/env;
- `.gitignore` защищает типовые private paths, но не удаляет пользовательские файлы;
- никаких upload в MinIO production автоматически;
- importer работает локально/на выделенном dataset host.

## Input

Поддержать extracted directory как обязательный канон. `.7z` может быть optional convenience
через system `7z`, но не добавляй сомнительную archive dependency только ради удобства.

Текущие архивы:

```text
ЖК Stories Кладка.7z
Мосфильмовская 31А Planswift.7z
```

## Parser

Реализуй PlanSwift-specific parser по reference contract:

- XML encoding fallback UTF-8→cp1251 с explicit counters;
- page identity/PageGUID;
- DigitizerData points;
- Area / Area Subtract parent relation;
- Linear Section;
- Count points;
- placeholders rejected with reason;
- ScaleX/ScaleY stored only as source evidence;
- source file SHA-256.

## Output

Версионный `planswift-gt-v1` JSONL/Parquet-like manifest. Выбери простой открытый формат,
который diff/validate можно воспроизвести без DB. Binary images остаются files by hash/path.

CLI команды минимум:

```text
inspect
convert
validate
stats
```

Synthetic fixture обязателен в git; реальные клиентские snippets не коммитить.

Сравни фактические counts с reference expectations, но не hardcode expected counts в parser.

Документ `docs/stage2b/06-planswift-import.md`.

STOP.
