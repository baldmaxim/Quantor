# Quantor — Stage 2A: Measurement Core

Этот пакет выполняется **после закрытого Stage 1.5**.

Цель Stage 2A — впервые научить Quantor **корректно измерять PDF-чертёж вручную** и
детерминированно получать count / length / area. На этом этапе **нет AI Auto Count,
Auto Measure, CV/VLM-инференса, ProjectGraph и BIM-разбора**.

Главная последовательность:

```text
Stage transition + preflight
        ↓
Canonical PDF Page Geometry
        ↓
Coordinate Transform Core
        ↓
Manual Scale Calibration
        ↓
Takeoff Item + Measurement Domain
        ↓
Measurement API
        ↓
Manual tools in Viewer
        ↓
Deterministic Quantity Engine
        ↓
Benchmark
        ↓
Live acceptance on real PDF
```

## Почему AI пока запрещён

Если ручная линия на известном размере не даёт правильные метры, AI поверх неё лишь
маскирует ошибку. Stage 2A должен отделить ошибки геометрии/масштаба/UX от будущих ошибок
детектора или VLM.

## Как выполнять

Использовать Claude Code, модель Opus 5 (1M). Запускать промты **строго по порядку**.
После каждого промта читать отчёт и проверять тесты. Claude не переходит к следующему
промту самостоятельно.

Рекомендуемое размещение:

```text
_prompts/stage2a_measurement_core/
```

Первый запуск:

```text
Прочитай полностью и выполни:
_prompts/stage2a_measurement_core/prompts/00_MASTER_STAGE2A_CONTEXT.md

Не переходи к следующему промту самостоятельно.
```

## Что считается результатом Stage 2A

На реальном PDF пользователь должен уметь:

1. открыть лист;
2. увидеть, что каноническая геометрия PDF известна серверу;
3. откалибровать масштаб по известному размеру;
4. создать Takeoff Item;
5. поставить Count или нарисовать Line / Polyline / Area;
6. получить воспроизводимый результат в штуках / м / м²;
7. выделить, отредактировать или удалить измерение;
8. увидеть источник результата: проект → документ → ревизия → лист → Measurement →
   ScaleCalibration → rule_version;
9. повторить тот же расчёт после перезапуска приложения и получить тот же результат;
10. пройти benchmark и live-acceptance без AI.

## Жёстко не входит

- AI Auto Count / Auto Measure;
- вызовы Claude/OpenAI/Qwen/VLM/CV в runtime;
- обучение Unsloth;
- автоматическое чтение масштаба из надписи `М 1:100`;
- автоматическое распознавание размерных линий;
- стены/двери/окна как семантические классы;
- вычитание проёмов и строительные правила;
- объём, масса, стоимость;
- BIM/Revit/Navisworks/IFC parsing;
- сравнение ревизий;
- ВОР как итоговый производственный отчёт.

Это будет Stage 2B+.
