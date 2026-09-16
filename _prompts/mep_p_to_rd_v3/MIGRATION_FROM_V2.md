# MIGRATION PATCH — v2 → v3 без перезапуска проекта

Используй этот промт, если работа уже начата по `Quantor_MEP_P_to_RD_Prompt_Pack_v2`.

---

Ты продолжаешь текущую работу Quantor MEP. **Не начинай проект заново, не откатывай выполненные изменения и не повторяй уже завершённые шаги.**

## Корректировка scope

Предыдущее правило `recognition is solved/frozen` было слишком широким.

С этого момента действует:

> **Base document recognition is solved and frozen.**  
> **MEP semantic recognition is NOT solved and IS IN SCOPE.**

### Frozen / read-only

Не менять без отдельного разрешения:
- PDF ingest;
- page rendering/rasterization;
- существующий vector extraction;
- OCR/text extraction;
- source coordinate transforms;
- общую инфраструктуру masks/points/polylines, если она уже существует;
- существующие модели/веса/датасеты монолита, кладки, дверей;
- production behavior существующего recognition flow.

### Новый разрешённый scope

Разрешено и требуется разработать поверх существующих артефактов:

`MEP Semantic Extraction Layer`

Для первого ВК PoC он должен уметь извлекать минимум те MEP-сущности и связи, которые реально нужны генератору: стояки/source anchors, приборы/terminals, оборудование, видимые инженерные линии, марки/диаметры/подписи и relations — точный минимальный taxonomy определить по реальным П-листам.

Цепочка:

```text
existing Quantor base recognition [FROZEN]
→ MEP semantic extraction [NEW]
→ MEP Evidence Graph
→ P→RD Generator
→ MEP Network Graph
→ Quantity Engine
→ Pricing
```

## Критически важно

1. Не создавать новый общий recognizer документов.
2. Не считать MEP-сущности уже существующими, пока это не подтверждено реальными output-файлами.
3. Если MEP semantic layer использует изображение, брать уже подготовленный page raster/crop из существующего pipeline; не строить второй PDF renderer.
4. Если использует текст — брать существующий OCR/text layer; не создавать второй OCR.
5. Ручная MEP-разметка допустима и нужна для GT/train/validation, но не должна становиться production-входом.
6. Не путать **Detection** и **Generation**:
   - detector отвечает «что реально показано на П?»;
   - generator отвечает «какая полноценная РД-система должна быть построена?».
7. `inferred` никогда не маркировать как `observed`.

## Что сделать сейчас

1. Зафиксируй, какие шаги v2 уже реально выполнены и какие файлы созданы/изменены.
2. Ничего не отменяй автоматически.
3. Перечитай текущий repository state.
4. Построй таблицу:

`Required MEP entity | already available | exact source | missing | proposed extraction method | GT needed`

5. Зафиксируй существующий base recognition boundary как read-only.
6. Вставь новый MEP semantic layer между base recognition и прежним `MepGenerationInput`/P→RD.
7. Если ранее созданный adapter полезен — переиспользуй его как base-artifact adapter; не удаляй только из-за смены терминологии.
8. Обнови state/plan документов так, чтобы последующие шаги использовали `MepEvidenceGraph`, а не предполагали готовые MEP anchors в legacy output.
9. Составь migration receipt:
   - что из v2 остаётся;
   - что меняется;
   - какие артефакты признаны устаревшими;
   - что делать следующим промтом v3.

## STOP

Не запускай обучение и не делай большой рефакторинг. Покажи migration receipt и дождись подтверждения, если требуется существенное изменение уже написанного кода.
