# Architecture Decision Records

Короткие записи о принятых архитектурных решениях. Формат: Контекст → Решение → Последствия →
Отвергнутые альтернативы.

ADR не переписываются задним числом. Если решение меняется — добавляется новая запись,
а старая помечается как заменённая.

| №                                                       | Решение                                                | Статус  |
| ------------------------------------------------------- | ------------------------------------------------------ | ------- |
| [0000](0000-otstuplenie-ot-obshchego-steka.md)          | Отступление от общего стека каталога Odintsov          | Принято |
| [0001](0001-granicy-monorepozitoriya.md)                | Границы монорепозитория                                | Принято |
| [0002](0002-hranenie-binarnyh-fajlov.md)                | Объектное хранилище для бинарных файлов                | Принято |
| [0003](0003-neizmenyaemye-revizii.md)                   | Неизменяемые Document + DocumentRevision               | Принято |
| [0004](0004-arhitektura-prosmotrshchika.md)             | Архитектура просмотрщика: base + overlay               | Принято |
| [0005](0005-abstrakciya-zadanij.md)                     | Абстракция асинхронных заданий                         | Принято |
| [0006](0006-shlyuz-modelej.md)                          | Шлюз моделей, нейтральный к провайдеру                 | Принято |
| [0007](0007-import-raspoznannogo-paketa.md)             | Импорт распознанного пакета legacy-v1                  | Принято |
| [0008](0008-koordinaty-i-proishozhdenie.md)             | Координаты и происхождение данных                      | Принято |
| [0009](0009-python-i-lokalnyj-tuling.md)                | Python 3.12 и локальный тулинг                         | Принято |
| [0010](0010-orkestrator-buduschego-konvejera.md)        | Оркестратор будущего конвейера                         | принято |
| [0011](0011-integraciya-s-tenderhub.md)                 | Интеграция с TenderHUB                                 | принято |
| [0012](0012-granica-autentifikacii-i-avtorizacii.md)    | Граница аутентификации и авторизации                   | принято |
| [0013](0013-granica-razvyortyvaniya-admin-console.md)   | Граница развёртывания админ-контура                    | принято |
| [0014](0014-otdelnyj-ispolnitel-zadanij.md)             | Отдельный исполнитель заданий                          | принято |
| [0015](0015-sloi-nalozheniya-na-canvas2d.md)            | Слои наложения на Canvas2D до замера                   | принято |
| [0016](0016-kanonicheskaya-geometriya-stranicy-pdf.md)  | Каноническая геометрия страницы PDF на сервере         | принято |
| [0017](0017-chislennaya-granica-hranenie-i-raschyot.md) | Численная граница: хранение десятичное, расчёт float64 | принято |
| [0018](0018-kalibrovka-masshtaba-cherteja.md)           | Калибровка масштаба: мм на точку PDF, неизменяемо      | принято |
| [0019](0019-takeoff-item-i-measurement.md)              | TakeoffItem и Measurement: строка обмера и геометрия   | принято |
