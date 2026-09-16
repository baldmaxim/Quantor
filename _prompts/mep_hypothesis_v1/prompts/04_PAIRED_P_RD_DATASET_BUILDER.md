# PROMPT 04 — Builder парного датасета П ↔ РД

Создай pipeline подготовки **парных** кейсов П→РД одного проекта. Это ключевой датасет для обучения достройки сети.

Единица данных: `(project_id, building/section, floor_id, discipline, subsystem)`.

Для каждого кейса:
1. Найди соответствующий план стадии П и соответствующий план РД.
2. Зафиксируй hashes/revisions и доказательство соответствия.
3. Выполни alignment в общей source/metric системе координат; сохрани transform и residual error.
4. Получи/подготовь `P MepEvidenceGraph` и `RD MepNetworkGraph`.
5. Рассчитай delta labels:
   - retained;
   - added in RD;
   - removed;
   - moved;
   - connectivity changed;
   - size/material/elevation changed;
   - accessory added.
6. Пометь неполные/неоднозначные пары HOLD, не использовать их как отрицательные примеры.
7. Split только по `project_id`; один проект полностью в одном fold.
8. Сформируй dataset manifest и quality dashboard.

Нужна ручная review queue для alignment и topology. Не пытайся “вылечить” плохую пару автоматически.

Выведи статистику не только в альбомах, но и в:
- projects;
- paired albums;
- usable floor-pairs;
- nodes/edges;
- route meters;
- unique symbols/types;
- design organizations;
- building typologies.

Добавь learning-curve manifest: train subsets 10%, 25%, 50%, 75%, 100% на фиксированном held-out project split.
