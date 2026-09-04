'use client';

import type { RegionRead } from '@quantor/api-client';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, use, useEffect, useMemo, useRef, useState } from 'react';

import { DrawingViewport } from '@/components/viewer/DrawingViewport';
import { useDocumentBackend } from '@/components/viewer/useDocumentBackend';
import { EmptyState, ErrorState, Field, InspectorSection, StatusBadge, cx } from '@/components/ui';
import {
  IconChevronLeft,
  IconChevronRight,
  IconCursor,
  IconEye,
  IconEyeOff,
  IconHand,
  IconLayers,
  IconReset,
  IconWarning,
  IconZoomIn,
  IconZoomOut,
} from '@/components/ui/icons';
import { ToolButton, ToolDivider, ToolField } from '@/components/workspace/Toolbar';
import { WorkspaceShell } from '@/components/workspace/WorkspaceShell';
import { errorMessage } from '@/lib/errors';
import { REGIONS_FORMS, blockType, countOf } from '@/lib/format';
import { useContentUrl, useProject, useRegions, useSheets } from '@/lib/queries';
import { Camera } from '@/lib/viewer/camera';
import { normalizeRotation } from '@/lib/viewer/coordinates';
import type { OverlayRegion } from '@/lib/viewer/overlay';
import { useWorkspaceStore, type LeftTab } from '@/store/workspace';

/**
 * Рабочая область: чертёж, распознанные области и их свойства.
 *
 * Что открыто — лист и выбранная область — живёт в адресе: ссылка на конкретный лист
 * должна работать. Всё остальное состояние эфемерно и лежит в небольшом хранилище.
 */

interface IPageProps {
  params: Promise<{ projectId: string }>;
}

const LEFT_TABS: readonly { id: LeftTab; label: string; enabled: boolean; hint?: string }[] = [
  { id: 'documents', label: 'Листы', enabled: true },
  { id: 'recognition', label: 'Распознавание', enabled: true },
  { id: 'takeoff', label: 'Обмеры', enabled: false, hint: 'Этап 2' },
];

const WorkspacePage = ({ params }: IPageProps) => {
  const { projectId } = use(params);
  const router = useRouter();
  const searchParams = useSearchParams();

  const revisionId = searchParams.get('revision');
  const pageParam = Number(searchParams.get('page') ?? '1');
  const selectedRegionId = searchParams.get('region');

  const project = useProject(projectId);
  const sheets = useSheets(revisionId);
  const content = useContentUrl(revisionId);
  const { backend, loading, errorCode } = useDocumentBackend(content.data?.url ?? null);

  const leftTab = useWorkspaceStore((state) => state.leftTab);
  const setLeftTab = useWorkspaceStore((state) => state.setLeftTab);
  const tool = useWorkspaceStore((state) => state.tool);
  const setTool = useWorkspaceStore((state) => state.setTool);
  const overlayVisible = useWorkspaceStore((state) => state.overlayVisible);
  const toggleOverlay = useWorkspaceStore((state) => state.toggleOverlay);
  const hiddenTypes = useWorkspaceStore((state) => state.hiddenTypes);
  const toggleType = useWorkspaceStore((state) => state.toggleType);

  const camera = useMemo(() => new Camera(), []);
  useEffect(() => () => camera.dispose(), [camera]);

  const [zoomPercent, setZoomPercent] = useState(100);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [regionSearch, setRegionSearch] = useState('');

  const pages = sheets.data?.items ?? [];
  const pageIndex = Math.min(Math.max(pageParam - 1, 0), Math.max(pages.length - 1, 0));
  const sheet = pages[pageIndex] ?? null;

  const regions = useRegions(sheet?.id ?? null, null);
  const overlayRegions = useMemo(() => toOverlayRegions(regions.data?.items ?? []), [regions.data]);
  const selectedRegion = regions.data?.items.find((item) => item.id === selectedRegionId) ?? null;

  const counts = useMemo(() => countByType(regions.data?.items ?? []), [regions.data]);

  const setQuery = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(searchParams.toString());
    for (const [key, value] of Object.entries(changes)) {
      if (value === null) next.delete(key);
      else next.set(key, value);
    }
    router.replace(`/projects/${projectId}/workspace?${next.toString()}`, { scroll: false });
  };

  const goToPage = (index: number) => {
    const clamped = Math.min(Math.max(index, 0), pages.length - 1);
    setQuery({ page: String(clamped + 1), region: null });
  };

  const viewportSheet = sheet
    ? {
        pageIndex: sheet.page_index,
        widthPx: sheet.width_px ?? 2481,
        heightPx: sheet.height_px ?? 3509,
        rotation: normalizeRotation(sheet.rotation),
      }
    : null;

  const failure = renderError ?? errorCode ?? null;

  return (
    <>
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
                  {sheet ? `Лист ${sheet.page_label ?? sheet.page_index + 1}` : 'Лист не выбран'}
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

              <ToolButton
                label="Предыдущий лист"
                disabled={pageIndex === 0}
                onClick={() => goToPage(pageIndex - 1)}
              >
                <IconChevronLeft width={16} height={16} />
              </ToolButton>
              <ToolField
                label="Номер листа"
                value={pages.length > 0 ? pageIndex + 1 : '—'}
                suffix={`/ ${pages.length || '—'}`}
              />
              <ToolButton
                label="Следующий лист"
                disabled={pageIndex >= pages.length - 1}
                onClick={() => goToPage(pageIndex + 1)}
              >
                <IconChevronRight width={16} height={16} />
              </ToolButton>

              <ToolDivider />

              <ToolButton label="Уменьшить" onClick={() => camera.zoomOut(viewportSize())}>
                <IconZoomOut width={16} height={16} />
              </ToolButton>
              <ToolField label="Масштаб вида" value={`${zoomPercent} %`} />
              <ToolButton label="Увеличить" onClick={() => camera.zoomIn(viewportSize())}>
                <IconZoomIn width={16} height={16} />
              </ToolButton>
              <ToolButton
                label="По ширине"
                wide
                onClick={() =>
                  viewportSheet && camera.fitWidth(sheetSize(viewportSheet), viewportSize())
                }
              >
                По ширине
              </ToolButton>
              <ToolButton
                label="Целиком"
                wide
                onClick={() =>
                  viewportSheet && camera.fitPage(sheetSize(viewportSheet), viewportSize())
                }
              >
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

              <ToolButton
                label="Сбросить вид"
                onClick={() =>
                  viewportSheet && camera.reset(sheetSize(viewportSheet), viewportSize())
                }
              >
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

              <div className="min-h-0 flex-1 overflow-auto overscroll-contain">
                {leftTab === 'documents' && (
                  <SheetList
                    pages={pages.map((item) => ({
                      id: item.id,
                      index: item.page_index,
                      label: item.page_label,
                      regionCount: item.region_count,
                    }))}
                    activeIndex={pageIndex}
                    onSelect={goToPage}
                  />
                )}

                {leftTab === 'recognition' && (
                  <RecognitionPanel
                    counts={counts}
                    hiddenTypes={hiddenTypes}
                    onToggleType={toggleType}
                    regions={regions.data?.items ?? []}
                    search={regionSearch}
                    onSearch={setRegionSearch}
                    selectedId={selectedRegionId}
                    onSelect={(id) => setQuery({ region: id })}
                  />
                )}

                {leftTab === 'takeoff' && (
                  <p className="p-[var(--s-4)] text-xs text-muted">
                    Обмеры появятся на этапе 2. Сейчас портал показывает то, что распознала
                    распознавалка, и ничего не вычисляет.
                  </p>
                )}
              </div>
            </>
          }
          center={
            <ViewportArea
              revisionId={revisionId}
              failure={failure}
              loading={loading || content.isPending}
              contentError={content.isError}
              projectId={projectId}
              onRetry={() => void content.refetch()}
            >
              <DrawingViewport
                backend={backend}
                sheet={viewportSheet}
                regions={overlayRegions}
                hiddenTypes={hiddenTypes}
                overlayVisible={overlayVisible}
                selectedId={selectedRegionId}
                onSelect={(id) => setQuery({ region: id })}
                camera={camera}
                tool={tool}
                onViewChange={(state) => setZoomPercent(Math.round(state.scale * 100))}
                onError={setRenderError}
              />
            </ViewportArea>
          }
          rightTitle="Свойства области"
          right={
            <div className="flex min-h-0 flex-1 flex-col gap-[var(--s-5)] overflow-auto overscroll-contain p-[var(--s-4)]">
              {selectedRegion ? (
                <RegionInspector
                  region={selectedRegion}
                  sheetLabel={sheetLabel(sheet, pages.length)}
                />
              ) : (
                <InspectorSection title="Ничего не выбрано">
                  <p className="text-xs text-muted">
                    Выберите область на чертеже — здесь появятся её идентификатор, тип, координаты и
                    распознанный текст.
                  </p>
                </InspectorSection>
              )}
            </div>
          }
          status={
            <>
              <span className="tabular">
                Лист {pages.length > 0 ? pageIndex + 1 : '—'} / {pages.length || '—'}
              </span>
              <span className="tabular">Масштаб вида {zoomPercent} %</span>
              {/* Определять масштаб чертежа портал не умеет и пишет об этом прямо. */}
              <span>Масштаб чертежа: Не задан</span>
              <span className="ml-auto flex gap-[var(--s-6)]">
                <span className="tabular">
                  {countOf(regions.data?.total ?? 0, REGIONS_FORMS)} на листе
                </span>
                <span>рендер: {backend?.name ?? 'не подключён'}</span>
                {sheet?.width_px && (
                  <span className="tabular">
                    {sheet.width_px} × {sheet.height_px} px
                  </span>
                )}
              </span>
            </>
          }
        />
      </div>
    </>
  );
};

/* ------------------------------------------------------------------ вспомогательное */

const viewportSize = () => {
  const element = document.querySelector('[data-testid="viewport"]');
  return element
    ? { width: element.clientWidth, height: element.clientHeight }
    : { width: 1200, height: 800 };
};

const sheetSize = (sheet: { widthPx: number; heightPx: number; rotation: number }) => {
  const swapped = sheet.rotation === 90 || sheet.rotation === 270;
  return {
    width: swapped ? sheet.heightPx : sheet.widthPx,
    height: swapped ? sheet.widthPx : sheet.heightPx,
  };
};

const sheetLabel = (
  sheet: { page_index: number; page_label: string | null } | null,
  total: number,
): string => (sheet ? `${sheet.page_label ?? sheet.page_index + 1} из ${total}` : '—');

const toOverlayRegions = (regions: readonly RegionRead[]): OverlayRegion[] =>
  regions
    .filter((region) => region.coords_norm.length === 4)
    .map((region) => ({
      id: region.id,
      blockType: region.block_type,
      shapeType: region.shape_type,
      coords: [
        region.coords_norm[0] ?? 0,
        region.coords_norm[1] ?? 0,
        region.coords_norm[2] ?? 0,
        region.coords_norm[3] ?? 0,
      ] as const,
      polygon:
        region.polygon_points?.map(
          (point) => [point[0] ?? 0, point[1] ?? 0] as readonly [number, number],
        ) ?? null,
    }));

const countByType = (regions: readonly RegionRead[]): Record<string, number> => {
  const counts: Record<string, number> = {};
  for (const region of regions) {
    counts[region.block_type] = (counts[region.block_type] ?? 0) + 1;
  }
  return counts;
};

/* ---------------------------------------------------------------------- состояния */

interface IViewportAreaProps {
  revisionId: string | null;
  failure: string | null;
  loading: boolean;
  contentError: boolean;
  projectId: string;
  onRetry: () => void;
  children: React.ReactNode;
}

const ViewportArea = ({
  revisionId,
  failure,
  loading,
  contentError,
  projectId,
  onRetry,
  children,
}: IViewportAreaProps) => {
  if (!revisionId) {
    return (
      <div className="grid h-full place-items-center p-[var(--s-7)]">
        <EmptyState
          title="Ревизия не выбрана"
          description="Откройте рабочую область из карточки проекта — она передаст сюда готовый документ."
          action={
            <Link
              href={`/projects/${projectId}`}
              className="text-sm text-accent underline underline-offset-4"
            >
              К карточке проекта
            </Link>
          }
        />
      </div>
    );
  }

  if (contentError || failure) {
    return (
      <div className="grid h-full place-items-center p-[var(--s-7)]">
        <ErrorState
          title="Документ не открылся"
          code={failure}
          description={failure ? errorMessage(failure) : 'Файл ревизии недоступен в хранилище.'}
          onRetry={onRetry}
        />
      </div>
    );
  }

  return (
    <>
      {children}
      {loading && (
        <div className="pointer-events-none absolute inset-0 grid place-items-center">
          <span className="rounded-[var(--radius-sm)] bg-surface px-[var(--s-5)] py-[var(--s-3)] text-xs text-muted">
            Открываем документ…
          </span>
        </div>
      )}
    </>
  );
};

/* ------------------------------------------------------------------- левая панель */

interface ISheetListProps {
  pages: readonly { id: string; index: number; label: string | null; regionCount: number }[];
  activeIndex: number;
  onSelect: (index: number) => void;
}

/**
 * Список листов.
 *
 * Показываются только видимые строки: у документа их 77, и держать в разметке все
 * вместе с миниатюрами значило бы рисовать весь документ ради панели шириной 264 px.
 */
const SheetList = ({ pages, activeIndex, onSelect }: ISheetListProps) => {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    container.current?.querySelector('[aria-current="true"]')?.scrollIntoView({ block: 'nearest' });
  }, [activeIndex]);

  if (pages.length === 0) {
    return <p className="p-[var(--s-4)] text-xs text-muted">Листов пока нет.</p>;
  }

  return (
    <div ref={container} className="flex flex-col py-[var(--s-2)]">
      {pages.map((page) => (
        <button
          key={page.id}
          type="button"
          aria-current={page.index === activeIndex}
          onClick={() => onSelect(page.index)}
          className={cx(
            'flex h-[var(--h-row-tree)] items-center gap-[var(--s-3)] px-[var(--s-4)] text-left text-xs transition-colors',
            page.index === activeIndex
              ? 'bg-accent-soft text-text'
              : 'text-muted hover:bg-surface-muted hover:text-text',
          )}
        >
          <span className="tabular w-[28px] flex-none">{page.label ?? page.index + 1}</span>
          <span className="min-w-0 flex-1 truncate">Лист {page.index + 1}</span>
          {page.regionCount > 0 && (
            <span className="tabular text-micro text-muted">{page.regionCount}</span>
          )}
        </button>
      ))}
    </div>
  );
};

interface IRecognitionPanelProps {
  counts: Record<string, number>;
  hiddenTypes: ReadonlySet<string>;
  onToggleType: (type: string) => void;
  regions: readonly RegionRead[];
  search: string;
  onSearch: (value: string) => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

const RecognitionPanel = ({
  counts,
  hiddenTypes,
  onToggleType,
  regions,
  search,
  onSearch,
  selectedId,
  onSelect,
}: IRecognitionPanelProps) => {
  const query = search.trim().toLowerCase();
  const filtered = query
    ? regions.filter(
        (region) =>
          region.external_block_id.toLowerCase().includes(query) ||
          region.block_type.toLowerCase().includes(query),
      )
    : regions;

  return (
    <div className="flex flex-col">
      <p className="px-[var(--s-4)] pt-[var(--s-4)] pb-[var(--s-2)] text-micro tracking-[0.06em] text-muted uppercase">
        Типы областей
      </p>

      <div className="flex flex-col gap-[var(--s-2)] px-[var(--s-4)] pb-[var(--s-4)]">
        {Object.entries(counts).map(([type, count]) => {
          const hidden = hiddenTypes.has(type);
          const Icon = hidden ? IconEyeOff : IconEye;

          return (
            <button
              key={type}
              type="button"
              onClick={() => onToggleType(type)}
              aria-pressed={!hidden}
              className={cx(
                'flex items-center gap-[var(--s-3)] text-xs transition-opacity',
                hidden && 'opacity-45',
              )}
            >
              <span
                aria-hidden="true"
                className="h-[11px] w-[11px] flex-none rounded-[3px] border-[1.5px]"
                style={{
                  borderColor: `var(--region-${type})`,
                  background: `var(--region-${type})`,
                }}
              />
              <span className="flex-1 text-left">{blockType(type)}</span>
              <span className="tabular text-micro text-muted">{count}</span>
              <Icon width={13} height={13} className="text-muted" />
            </button>
          );
        })}
      </div>

      <div className="px-[var(--s-4)] pb-[var(--s-3)]">
        <input
          value={search}
          onChange={(event) => onSearch(event.target.value)}
          placeholder="Поиск по block_id"
          aria-label="Поиск области"
          className="h-[var(--h-ctl-ws)] w-full rounded-[var(--radius-sm)] border border-border-control bg-surface px-[var(--s-4)] text-xs"
        />
      </div>

      <div className="flex flex-col">
        {filtered.map((region) => (
          <button
            key={region.id}
            type="button"
            onClick={() => onSelect(region.id)}
            className={cx(
              'flex h-[var(--h-row-region)] items-center gap-[var(--s-3)] px-[var(--s-4)] text-left text-xs transition-colors',
              region.id === selectedId
                ? 'bg-accent-soft text-text'
                : 'text-muted hover:bg-surface-muted hover:text-text',
            )}
          >
            <span
              aria-hidden="true"
              className="h-[8px] w-[8px] flex-none rounded-[2px]"
              style={{ background: `var(--region-${region.block_type})` }}
            />
            <span className="min-w-0 flex-1 truncate">
              {region.ordinal ? `#${region.ordinal} · ` : ''}
              {blockType(region.block_type)}
            </span>
            <span className="mono flex-none text-micro text-muted">
              {region.external_block_id.slice(0, 10)}
            </span>
          </button>
        ))}

        {filtered.length === 0 && (
          <p className="px-[var(--s-4)] py-[var(--s-3)] text-xs text-muted">
            {regions.length === 0 ? 'На листе нет распознанных областей.' : 'Ничего не найдено.'}
          </p>
        )}
      </div>
    </div>
  );
};

/* ---------------------------------------------------------------------- инспектор */

const RegionInspector = ({ region, sheetLabel }: { region: RegionRead; sheetLabel: string }) => {
  const cropUrl = region.legacy_metadata['crop_url'];

  return (
    <>
      <InspectorSection title={blockType(region.block_type)}>
        <dl className="grid grid-cols-[92px_1fr] gap-x-[var(--s-4)] gap-y-[var(--s-2)]">
          <Field label="block_id">{region.external_block_id}</Field>
          {region.ordinal !== null && <Field label="Номер">{region.ordinal}</Field>}
          <Field label="Лист">{sheetLabel}</Field>
          <Field label="Форма">{region.shape_type}</Field>
          <Field label="Координаты">
            [{region.coords_norm.map((value) => value.toFixed(3)).join(', ')}]
          </Field>
          <Field label="Простр-во">normalized_page_top_left</Field>
          {region.recognition_status && <Field label="Статус">{region.recognition_status}</Field>}
        </dl>
      </InspectorSection>

      {region.raw_content_md && (
        <InspectorSection title="Распознанный текст">
          {/* Текст пришёл из недоверенного архива и показывается как текст, а не как
              разметка: разбирать его как HTML нельзя. */}
          <pre className="mono max-h-[240px] overflow-auto rounded-[var(--radius-sm)] border border-border bg-surface-sunken p-[var(--s-3)] text-micro leading-relaxed whitespace-pre-wrap text-muted">
            {region.raw_content_md}
          </pre>
        </InspectorSection>
      )}

      {typeof cropUrl === 'string' && (
        <InspectorSection title="Исходные метаданные">
          <p className="flex items-start gap-[var(--s-3)] text-micro text-muted">
            <IconWarning width={13} height={13} className="mt-[2px] flex-none text-warning" />
            {/* Сервер эту ссылку не загружает: пакет должен оставаться самодостаточным. */}
            <span className="min-w-0 break-all">
              crop_url — внешняя ссылка, сервер её не загружает: {cropUrl}
            </span>
          </p>
        </InspectorSection>
      )}
    </>
  );
};

const WorkspaceRoute = ({ params }: IPageProps) => (
  <Suspense fallback={null}>
    <WorkspacePage params={params} />
  </Suspense>
);

export default WorkspaceRoute;
