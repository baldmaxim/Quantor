# Stage 1 routes and UI map

Desktop-first application. Workspace optimized for 1440p/1920p. For narrow/mobile screens, project list may remain usable, but drawing workspace may show a clear desktop-required message.

## Routes

```text
/                         -> redirect to /projects
/projects                 -> project dashboard
/projects/new             -> optional route or modal-backed route
/projects/:projectId      -> project overview
/projects/:projectId/workspace -> drawing workspace
/settings                 -> shell/placeholder
```

Future routes may exist in nav but must be visibly disabled and labeled “Позже” / feature flag:

```text
/templates
/models
/reports
/admin/models
```

## Global shell

- compact left navigation rail;
- product name/logo placeholder, no borrowed Kreo assets;
- Projects active;
- Templates / Models / Reports disabled or feature-flagged;
- settings/user menu placeholder;
- dark/light theme possible, but drawing workspace defaults to a low-glare dark chrome around a neutral drawing canvas.

## Projects page

- header “Проекты”;
- search;
- sort by recent/name;
- grid/list toggle optional;
- project cards/rows with name, document count, status, updated time;
- “Создать проект” primary action;
- empty, loading, failed states;
- no fake financial metrics.

## Create Project flow

- project name;
- drag/drop files;
- primary supported Stage 1 input: recognized ZIP;
- optional raw PDF upload stored as document with status `unprocessed`;
- RVT/NWD/NWC/IFC can be accepted/stored but show “processor not enabled”; do not parse;
- upload progress;
- background import status;
- safe error messages.

## Project overview

- project name and status;
- Documents card/list;
- recognition/import status;
- latest activity placeholder;
- button “Открыть рабочую область”.

## Workspace

Three-pane shell:

```text
+------------------------------------------------------------------+
| breadcrumb/project | open page tabs | job status | user          |
+-------------+--------------------------------------+-------------+
| Documents / |                                      | Inspector / |
| Layers      |          Drawing viewport            | Details     |
|             |                                      |             |
| page tree   |                                      |             |
| regions     |                                      |             |
+-------------+--------------------------------------+-------------+
| page | zoom | scale:not set | backend | coords/debug             |
+------------------------------------------------------------------+
```

### Left panel Stage 1
Tabs:
- Documents: files + sheet/page tree;
- Recognition: block types/text/image/stamp and visibility toggles;
- Takeoff: disabled placeholder “Этап 2”.

### Viewer toolbar Stage 1
- pointer / pan mode;
- previous/next page;
- page input;
- zoom out/in;
- fit width/fit page;
- text search button placeholder or basic PDF search if easy;
- recognition overlay toggle;
- scale indicator `Не задан` — no scale engine yet.

### Right inspector Stage 1
When a region is selected:
- block id;
- block type;
- page;
- normalized coordinates;
- status;
- raw recognized Markdown payload if present (sanitized/plain, collapsible);
- legacy crop URL only as metadata; do not server-fetch.

No properties for takeoff measurements yet.
