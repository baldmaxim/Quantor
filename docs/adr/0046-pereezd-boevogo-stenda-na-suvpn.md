# ADR-0046. Переезд боевого стенда на сервер suvpn

Статус: принято, 2026-11-13. Дополняет [ADR-0032](0032-boevoe-razvyortyvanie-na-selectel.md): пункты про
сервер (1) и ресурсы заменены, остальное — DNS, nginx, MinIO, `update.sh`, `RELEASE`, `.env` — без изменений.

## Контекст

Стенд Quantor жил на Selectel VDS 2-4-50 (SSH-алиас `quantor`) вместе с соседями — TG_Info, MailHub,
ServerControl, VPN. На 2 vCPU / 4 ГБ портал, воркер разбора PDF и CAD-исполнитель упирались в
память и процессор, диск был занят на 90 %. Владелец решил перенести Quantor на отдельный сервер
`suvpn`.

## Решение

1. **Боевой сервер Quantor — `suvpn`** (SSH-алиас в `~/.ssh/config`, адрес в репозитории не хранится):
   4 vCPU / 16 ГБ / 493 ГБ, swap 8 ГБ, Ubuntu 24.04. Из соседей — только VPN AmneziaWG
   (контейнер `amnezia-awg2`, свои правила ufw); выкладка Quantor его не трогает.
2. **Раскладка та же, что в ADR-0032:** `/opt/portals/quantor` (compose-проект `quantor`, `.env`, `RELEASE`,
   скрипты) и `/opt/infra/nginx` (infra-nginx и certbot, сеть `infra_web`). Домены те же —
   `quantor.meridianai.ru` и `admin.quantor.meridianai.ru`; DNS переключён на suvpn.
3. **Данные перенесены целиком:** тома `quantor_db_data` и `quantor_minio_data` скопированы как есть при
   остановленном стеке, `.env` и сертификат Let's Encrypt — без изменений. Первый выпуск на suvpn —
   `23fe9d9`.
4. **На suvpn в ufw открыты 80/tcp, 443/tcp и 8443/udp** (HTTP/3 infra-nginx). Остальные правила сервера
   (SSH, VPN) не менялись.
5. **Старый сервер `quantor` выведен из выкладки:** стек `quantor-*` остановлен, тома оставлены для
   отката; `update.sh` там заменён заглушкой, которая отменяет выкладку (прежний —
   `update.sh.moved-20261113`, пояснение — `MOVED.txt`). На время переключения DNS там стоял
   мост nginx на suvpn; после переключения он снят в тот же день, сайта Quantor в infra-nginx
   старого сервера нет (прежний конфиг — `/opt/infra/nginx/quantor.conf.bak-premigrate-20261113`).
   Соседи на старом сервере работают как раньше.
6. **Выкладка:** `ssh suvpn "/opt/portals/quantor/update.sh <git-sha>"`; `deploy/ship-local.sh` по
   умолчанию выкатывает на `suvpn` (`QUANTOR_SSH`).

## Последствия

- Пределы памяти в `deploy/docker-compose.yml` подняты под 16 ГБ в тот же день: db 2g (`shared_buffers` 1GB,
  `max_connections` 80), api 2g и 4 процесса, worker и cad-worker 4g / swap 6g (CAD — 2 CPU), minio 1g,
  web 768m, admin 512m; около 2 ГБ оставлено ОС и VPN.
- Часовой пояс suvpn — UTC: резервная копия по cron `17 3 * * *` идёт в 03:17 UTC.
- Серверу suvpn нужен вход в GHCR (`docker login ghcr.io`, токен `read:packages` вводит владелец), иначе
  `update.sh` не скачает образы; без входа — только `ship-local.sh` / `SKIP_PULL=1`.
- Тома `quantor_*` на старом сервере удаляются только отдельным решением владельца.

## Отклонённые варианты

- **Смена тарифа на Selectel (ADR-0032, п. 1).** Не решает соседство на одном ingress и диске.
- **Чистая установка на suvpn.** Потеря пользователей, проектов и загруженных документов пилота.
