'use client';

import Link from 'next/link';
import { use } from 'react';

import { EmptyState, InspectorSection, StatusBadge, cx } from '@/components/ui';
import {
  IconCursor,
  IconHand,
  IconChevronLeft,
  IconChevronRight,
  IconLayers,
  IconReset,
  IconZoomIn,
  IconZoomOut,
} from '@/components/ui/icons';
import { ToolButton, ToolDivider, ToolField } from '@/components/workspace/Toolbar';
import { WorkspaceShell } from '@/components/workspace/WorkspaceShell';
import { REGIONS_FORMS, countOf } from '@/lib/format';
import { useProject } from '@/lib/queries';
import { useWorkspaceStore, type LeftTab } from '@/store/workspace';

/**
 * Рабочая область.
 *
 * На этом шаге собран весь хром: вкладки листов, инструменты, три панели, статусная
 * строка. Центр — заглушка: просмотрщик PDF и слой распознанных областей встают сюда
 * в промте 07, и раскладку для этого менять не придётся.
 *
 * Маршрут намеренно вне группы (portal): у рабочей области своя рейка и свои отступы,
 * а общий каркас страничных маршрутов отнял бы у чертежа высоту.
 */

interface IPageProps {
  params: Promise<{ projectId: string }>;
}

const LEFT_TABS: readonly { id: LeftTab; label: string; enabled: boolean; hint?: string }[] = [
  { id: 'documents', label: 'Документы', enabled: true },
  { id: 'recognition', label: 'Распознавание', enabled: true },
  { id: 'takeoff', label: 'Обмеры', enabled: false, hint: 'Этап 2' },
];

const WorkspacePage = ({ params }: IPageProps) => {
  const { projectId } = use(params);
  const project = useProject(projectId);

  const leftTab = useWorkspaceStore((state) => state.leftTab);
  const setLeftTab = useWorkspaceStore((state) => state.setLeftTab);
  const tool = useWorkspaceStore((state) => state.tool);
  const setTool = useWorkspaceStore((state) => state.setTool);
  const overlayVisible = useWorkspaceStore((state) => state.overlayVisible);
  const toggleOverlay = useWorkspaceStore((state) => state.toggleOverlay);

  return (
    <>
      {/* Ниже 1024 px чертёж работать не будет: три панели не помещаются.
          Честное сообщение лучше сломанной вёрстки. */}
      <div className="flex flex-1 flex-col items-center justify-center gap-[var(--s-5)] px-[var(--s-7)] text-center lg:hidden">
        <h1 className="text-lg font-medium">Нужен экран шире</h1>
        <p className="max-w-[42ch] text-sm text-muted">
          Рабочая область с чертежом рассчитана на десктоп от 1024 px. Список проектов и карточка
          проекта работают и на узком экране.
        </p>
        <Link
          href={`/projects/${projectId}`}
          className="text-sm text-accent underline underline-offset-4"
        >
          Вернуться к проекту
        </Link>
      </div>

      <div className="hidden min-h-0 flex-1 lg:flex lg:flex-col">
        <WorkspaceShell
          tabs={
            <>
              <div className="flex min-w-0 items-center gap-[var(--s-3)] border-r border-border px-[var(--s-5)] text-xs text-muted">
                <Link href="/projects" className="transition-colors hover:text-text">
                  Проекты
                </Link>
                <span aria-hidden="true" className="opacity-60">
                  /
                </span>
                <Link
                  href={`/projects/${projectId}`}
                  className="max-w-[220px] truncate text-text transition-colors hover:text-accent"
                >
                  {project.data?.name ?? '…'}
                </Link>
              </div>

              <div className="flex min-w-0 flex-1 items-stretch">
                <span className="flex items-center gap-[var(--s-3)] border-r border-border bg-surface-muted px-[var(--s-5)] text-xs shadow-[inset_0_-2px_0_var(--accent)]">
                  Лист не выбран
                </span>
              </div>

              <div className="flex items-center px-[var(--s-5)]">
                <StatusBadge tone="neutral">Заданий нет</StatusBadge>
              </div>
            </>
          }
          toolbar={
            <>
              <ToolButton
                label="Выбор"
                hint="V"
                active={tool === 'pointer'}
                onClick={() => setTool('pointer')}
              >
                <IconCursor width={16} height={16} />
              </ToolButton>
              <ToolButton
                label="Панорама"
                hint="пробел с перетаскиванием"
                active={tool === 'pan'}
                onClick={() => setTool('pan')}
              >
                <IconHand width={16} height={16} />
              </ToolButton>

              <ToolDivider />

              <ToolButton label="Предыдущий лист" disabled>
                <IconChevronLeft width={16} height={16} />
              </ToolButton>
              <ToolField value="—" suffix="/ —" label="Номер листа" />
              <ToolButton label="Следующий лист" disabled>
                <IconChevronRight width={16} height={16} />
              </ToolButton>

              <ToolDivider />

              <ToolButton label="Уменьшить" disabled>
                <IconZoomOut width={16} height={16} />
              </ToolButton>
              <ToolField value="—" label="Масштаб вида" />
              <ToolButton label="Увеличить" disabled>
                <IconZoomIn width={16} height={16} />
              </ToolButton>
              <ToolButton label="По ширине" wide disabled>
                По ширине
              </ToolButton>
              <ToolButton label="Целиком" wide disabled>
                Целиком
              </ToolButton>

              <ToolDivider />

              <ToolButton
                label="Слой распознавания"
                wide
                active={overlayVisible}
                onClick={toggleOverlay}
              >
                <IconLayers width={16} height={16} />
                Распознавание
              </ToolButton>
              <ToolButton label="Обмеры" hint="Этап 2" wide disabled>
                Обмеры
              </ToolButton>

              <span className="flex-1" />

              <ToolButton label="Сбросить вид" disabled>
                <IconReset width={16} height={16} />
              </ToolButton>
            </>
          }
          leftTitle={project.data?.name ?? '…'}
          left={
            <>
              <div
                role="tablist"
                aria-label="Разделы панели"
                className="flex border-b border-border"
              >
                {LEFT_TABS.map((tab) => (
                  <button
                    key={tab.id}
                    type="button"
                    role="tab"
                    aria-selected={leftTab === tab.id}
                    disabled={!tab.enabled}
                    title={tab.hint ? `${tab.label} — ${tab.hint}` : tab.label}
                    onClick={() => tab.enabled && setLeftTab(tab.id)}
                    className={cx(
                      'flex-1 border-r border-border py-[var(--s-3)] text-xs transition-colors last:border-r-0',
                      leftTab === tab.id
                        ? 'text-text shadow-[inset_0_-2px_0_var(--accent)]'
                        : 'text-muted',
                      tab.enabled ? 'hover:text-text' : 'cursor-not-allowed opacity-40',
                    )}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>

              <div className="min-h-0 flex-1 overflow-auto overscroll-contain p-[var(--s-4)]">
                {leftTab === 'takeoff' ? (
                  <p className="text-xs text-muted">
                    Обмеры появятся на этапе 2. Сейчас портал показывает то, что распознала
                    распознавалка, и ничего не вычисляет.
                  </p>
                ) : (
                  <p className="text-xs text-muted">
                    Здесь появятся документы, листы и области — после подключения просмотрщика.
                  </p>
                )}
              </div>
            </>
          }
          center={
            <div className="grid h-full place-items-center p-[var(--s-7)]">
              <EmptyState
                title="Просмотрщик подключается"
                description="Чертёж и слой распознанных областей появятся здесь на следующем шаге. Каркас рабочей области готов и меняться не будет."
              />
            </div>
          }
          rightTitle="Свойства области"
          right={
            <>
              <div className="flex min-h-0 flex-1 flex-col gap-[var(--s-5)] overflow-auto overscroll-contain p-[var(--s-4)]">
                <InspectorSection title="Ничего не выбрано">
                  <p className="text-xs text-muted">
                    Выберите область на чертеже — здесь появятся её идентификатор, тип, координаты и
                    распознанный текст.
                  </p>
                </InspectorSection>
              </div>
            </>
          }
          status={
            <>
              <span className="tabular">Лист — / —</span>
              <span className="tabular">Масштаб вида —</span>
              {/* Определять масштаб чертежа портал не умеет, и пишет об этом прямо. */}
              <span>Масштаб чертежа: Не задан</span>
              <span className="ml-auto flex gap-[var(--s-6)]">
                <span className="tabular">{countOf(0, REGIONS_FORMS)} на листе</span>
                <span>рендер: не подключён</span>
              </span>
            </>
          }
        />
      </div>
    </>
  );
};

export default WorkspacePage;
