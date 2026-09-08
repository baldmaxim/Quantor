# PROMPT 08 — Measurement API + efficient current-sheet loading

Построй OpenAPI для ручного takeoff.

## Endpoints

Спроектируй компактный набор для:

- list/create/update/archive TakeoffItem;
- list Measurements current sheet;
- create/update/delete Measurement;
- bounded batch create для Count/manual repeated clicks;
- authoritative value preview/read (может появиться окончательно в Prompt 12).

Не делай один endpoint на каждое поле.

## Performance

- current viewer грузит только measurements текущего sheet/relevant items;
- никаких N+1 по item count;
- pagination/bounded payload;
- batch max size явно ограничен и тестируется;
- batch atomic или чётко документированный partial-result contract;
- Count UI не обязан ждать roundtrip на каждый клик.

## Concurrency

Update использует optimistic version/If-Match-equivalent. Старый client не должен молча
перетереть новую geometry. 409 с понятным domain error.

## Authorization

Все object IDs проходят tenant/project checks. Проверить malicious combinations:

- item из Project A + sheet Project B;
- calibration другого sheet;
- measurement UUID чужого workspace;
- archived/deleted item;
- source=ai через manual endpoint.

## Audit

Логировать committed create/update/delete/batch summary, но не каждый pointer move.
Не складывать весь массив тысяч координат в audit metadata, если это раздувает журнал;
достаточно id/hash/count + важные before/after facts.

## Client

Regenerate OpenAPI/TS. Ни одного ручного DTO.

STOP после API tests и query-count tests.
