# PROMPT 04 — Frontend design system + application shell

Прочитай master context и `reference/ROUTES_AND_UI.md`.

Цель: построить визуально качественную, сдержанную, desktop-first оболочку QTO Portal, вдохновлённую удобством Kreo, но без копирования бренда/asset'ов/пиксельного дизайна.

## Design direction

Продукт должен ощущаться как инженерный профессиональный инструмент, а не generic SaaS landing page.

- высокая информационная плотность;
- спокойная нейтральная палитра;
- drawing workspace with dark chrome, neutral canvas;
- хорошо читаемые границы панелей;
- минимум decorative animation;
- tooltips у icon-only actions;
- keyboard/focus accessibility;
- consistent 4/8px spacing rhythm;
- no giant cards/headings inside workspace.

Можно использовать system font stack/Inter-like available font; не тащи шрифты ради украшения.

## Components

Создай reusable primitives только по мере необходимости:
- AppShell;
- SideNav;
- TopBar;
- Pane / ResizablePane;
- EmptyState;
- StatusBadge;
- ProgressRow;
- FileDropzone visual component;
- SearchInput;
- ProjectCard/ProjectRow;
- ToolbarButton;
- InspectorSection;
- ErrorBoundary / loading skeletons.

Используй существующие Radix/shadcn primitives, не переписывай accessibility components вручную.

## Routes

Реализуй shell routes:
- `/projects`;
- `/projects/[projectId]`;
- `/projects/[projectId]/workspace`;
- `/settings` placeholder.

Future nav items могут быть disabled: Templates, Models, Reports. Не создавать fake functionality.

## Workspace shell

Сделай 3-pane layout:
- left pane resize/collapse;
- center viewport placeholder;
- right inspector resize/collapse;
- top project/page strip;
- bottom status bar.

Сразу заложи slots/interfaces так, чтобы Prompt 07 вставил viewer без переписывания layout.

Не реализовывай measurement tools. В left pane Takeoff tab показывай честный disabled placeholder “Этап 2”.

## Data

Используй API client + TanStack Query. Для страниц, где backend data ещё не хватает, используй typed demo fixture только в Story/dev mode, не смешивай mock с production path.

## State discipline

- server state — TanStack Query;
- URL — selected project/document/sheet where meaningful;
- ephemeral workspace UI — small Zustand store;
- никаких giant context providers.

## Quality

- keyboard focus visible;
- dark/light theme if легко, но не в ущерб сроку;
- desktop target 1280+;
- no horizontal overflow in projects pages;
- workspace mobile/narrow mode communicates limitation instead of broken layout.

## Tests

- shell navigation;
- panel collapse/resize state;
- loading/error/empty states;
- accessibility smoke tests;
- screenshot/Playwright smoke at 1440x900 and 1920x1080 if current test infra supports.

## Acceptance

После этого шага портал выглядит как реальный инженерный продукт, но center viewport ещё может быть placeholder. Никаких AI/QTO действий.
