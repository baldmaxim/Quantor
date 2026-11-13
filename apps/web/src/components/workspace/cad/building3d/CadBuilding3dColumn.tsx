'use client';

import { cx } from '@quantor/ui';
import type { CadBuilding3dFloorRead } from '@quantor/api-client';
import { useMemo, useState, type FC } from 'react';

import { Button } from '@/components/ui';
import {
  alignmentNote,
  describeFloor,
  filterFloorsByGroup,
  floorKey,
  formatElevation,
  resolveGroupKey,
  splitFloors,
} from '@/lib/cad/building3d-geometry';
import { useCadBuilding3d } from '@/lib/cad/building3d-queries';
import { cadErrorText } from '@/lib/cad/errors';

import { CadBuilding3dCanvas } from './CadBuilding3dCanvas';
import { CadBuilding3dGroupSelect } from './CadBuilding3dGroupSelect';

export interface ICadBuilding3dColumnProps {
  readonly projectId: string;
  /** Открытый сейчас лист: этаж с тем же заданием, страницей и видом выделяется акцентом. */
  readonly current: { readonly jobId: string; readonly pageIndex: number; readonly view: number } | null;
  readonly onSelectFloor: (floor: CadBuilding3dFloorRead) => void;
  /** `column` - боковая колонка рабочей области (по умолчанию); `page` - вид на всю страницу. */
  readonly layout?: 'column' | 'page';
}

interface IHover {
  readonly key: string;
  readonly anchor: { readonly x: number; readonly y: number } | null;
}

const ROW =
  'flex min-h-[44px] w-full items-center justify-between gap-[var(--s-3)] px-[var(--s-4)] py-[var(--s-2)] text-left text-sm transition-colors motion-reduce:transition-none hover:bg-bg focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent';

// Вид `page`: холст на основную площадь, список этажей справа (от lg) или под холстом (уже).
const PAGE_ASIDE = 'flex h-full min-h-0 min-w-0 flex-1 flex-col bg-surface';
const PAGE_BODY = 'flex min-h-0 flex-1 flex-col overflow-y-auto [overscroll-behavior:contain] lg:flex-row lg:overflow-hidden';
const PAGE_CANVAS = 'relative h-[60dvh] min-h-[320px] min-w-0 flex-none lg:h-auto lg:min-h-0 lg:flex-1';
const PAGE_LIST =
  'min-h-[200px] flex-none divide-y divide-border overflow-auto border-t border-border [overscroll-behavior:contain] lg:min-h-0 lg:w-[280px] lg:border-l lg:border-t-0';

// Вид `column` (рабочая область): прежняя разметка без изменений.
const COLUMN_ASIDE =
  'flex flex-none flex-col border-b border-border bg-surface lg:h-full lg:w-[280px] lg:border-b-0 lg:border-r';
const COLUMN_BODY = 'flex min-h-0 flex-1 flex-row lg:flex-col';
const COLUMN_CANVAS = 'relative min-h-0 min-w-0 flex-1 basis-1/2 lg:min-h-[200px] lg:basis-auto';
const COLUMN_LIST =
  'min-h-0 flex-1 basis-1/2 divide-y divide-border overflow-auto border-l border-border [overscroll-behavior:contain] lg:max-h-[45%] lg:flex-none lg:basis-auto lg:border-l-0 lg:border-t';

/**
 * Колонка «Здание» вида «3D»: аксонометрия стопки этажей и список этажей одного здания (корпус +
 * секция; при нескольких - переключатель). Действующее здание: ручной выбор (только пока открыт тот же
 * лист, при котором он сделан), иначе здание открытого листа, иначе первое. Этажи уже совмещены сервером по
 * осям; несовмещённые помечены в списке и в подсказке. Щелчок по этажу на
 * холсте или в списке открывает его лист в основном 3D-виде. Этаж без отметки в 3D не строится
 * и стоит в списке внизу. Вид `column`: от `lg` - колонка слева; уже - сворачиваемая полоса сверху.
 * Вид `page`: на всю страницу, без сворачивания.
 */
export const CadBuilding3dColumn: FC<ICadBuilding3dColumnProps> = ({
  projectId,
  current,
  onSelectFloor,
  layout = 'column',
}) => {
  const isPage = layout === 'page';
  const query = useCadBuilding3d(projectId, true);
  const [open, setOpen] = useState(true);
  const [hover, setHover] = useState<IHover | null>(null);
  const [canvasError, setCanvasError] = useState<string | null>(null);
  // Ручной выбор помнит лист, при котором он сделан: смена листа его отменяет (без эффекта, при рендере).
  const [chosen, setChosen] = useState<{ readonly group: string; readonly sheetKey: string | null } | null>(null);

  const currentKey = current ? floorKey({ job_id: current.jobId, page_index: current.pageIndex, view: current.view }) : null;
  const groups = useMemo(() => query.data?.groups ?? [], [query.data]);
  const sheetGroup = useMemo(
    () => (query.data?.floors ?? []).find((item) => floorKey(item) === currentKey)?.group_key ?? null,
    [query.data, currentKey],
  );
  // Выбор для другого листа забывается совсем: возврат на прежний лист не вернёт старый выбор.
  if (chosen !== null && chosen.sheetKey !== currentKey) setChosen(null);
  const chosenGroup = chosen !== null && chosen.sheetKey === currentKey ? chosen.group : null;
  const groupKey = resolveGroupKey(groups, chosenGroup, sheetGroup);
  const floors = useMemo(
    () => filterFloorsByGroup(query.data?.floors ?? [], groupKey),
    [query.data, groupKey],
  );
  const list = useMemo(() => splitFloors(floors), [floors]);
  const byKey = useMemo(() => new Map(floors.map((floor) => [floorKey(floor), floor])), [floors]);
  const hovered = hover ? (byKey.get(hover.key) ?? null) : null;
  const hoveredNote = hovered ? alignmentNote(hovered, floors.length) : null;
  const hasFloors = list.known.length + list.unknown.length > 0;

  const select = (key: string) => {
    const floor = byKey.get(key);
    if (floor) onSelectFloor(floor);
  };

  const renderRow = (floor: CadBuilding3dFloorRead) => {
    const key = floorKey(floor);
    const isCurrent = key === currentKey;
    const note = alignmentNote(floor, floors.length);
    return (
      <li key={key}>
        <button
          type="button"
          aria-current={isCurrent ? 'true' : undefined}
          title={note?.title ?? undefined}
          className={cx(ROW, isCurrent ? 'bg-bg text-accent' : 'text-text')}
          onClick={() => onSelectFloor(floor)}
          onMouseEnter={() => setHover({ key, anchor: null })}
          onMouseLeave={() => setHover(null)}
          onFocus={() => setHover({ key, anchor: null })}
          onBlur={() => setHover(null)}
        >
          <span className="min-w-0 [overflow-wrap:anywhere]">
            {floor.label}
            {note && (
              <span className={cx('block text-xs', note.warn ? 'text-warning' : 'text-muted')}>
                {note.text}
              </span>
            )}
          </span>
          <span className="flex-none text-xs text-muted">
            {floor.elevation_known ? formatElevation(floor.base_z_mm) : 'отметка не определена'}
          </span>
        </button>
      </li>
    );
  };

  let body;
  if (query.isPending) {
    body = (
      <p role="status" className="p-[var(--s-5)] text-sm text-muted">
        Загружаем здание…
      </p>
    );
  } else if (query.isError) {
    body = (
      <div className="flex flex-col items-start gap-[var(--s-3)] p-[var(--s-5)]">
        <p role="alert" className="text-sm text-danger [overflow-wrap:anywhere]">
          {cadErrorText(query.error)}
        </p>
        <Button className="max-md:h-[44px]" onClick={() => void query.refetch()}>
          Повторить
        </Button>
      </div>
    );
  } else if (!hasFloors) {
    body = (
      <p role="status" className="p-[var(--s-5)] text-sm text-muted">
        Нет листов с конструкциями
      </p>
    );
  } else {
    body = (
      <div className={isPage ? PAGE_BODY : COLUMN_BODY}>
        <div className={isPage ? PAGE_CANVAS : COLUMN_CANVAS}>
          {list.known.length > 0 && canvasError === null && (
            <CadBuilding3dCanvas
              floors={floors}
              currentKey={currentKey}
              hoverKey={hover?.key ?? null}
              onHover={(key, anchor) => setHover(key === null ? null : { key, anchor })}
              onSelect={select}
              onError={setCanvasError}
            />
          )}
          {canvasError !== null && (
            <p role="alert" className="p-[var(--s-4)] text-xs text-danger">
              {canvasError}
            </p>
          )}
          {list.known.length === 0 && (
            <p role="status" className="p-[var(--s-4)] text-xs text-muted">
              Ни у одного этажа не определена отметка: в 3D нечего строить.
            </p>
          )}
          {hovered && hover?.anchor && (
            <div
              role="tooltip"
              className="pointer-events-none absolute z-10 max-w-[220px] rounded-[var(--radius-sm)] border border-border bg-surface px-[var(--s-3)] py-[var(--s-2)] text-xs text-text"
              style={{ left: Math.max(0, hover.anchor.x + 12), top: Math.max(0, hover.anchor.y + 12) }}
            >
              {describeFloor(hovered)}
              {hoveredNote?.warn && `, ${hoveredNote.text}`}
            </div>
          )}
        </div>
        <ul className={isPage ? PAGE_LIST : COLUMN_LIST}>
          {list.known.map(renderRow)}
          {list.unknown.map(renderRow)}
        </ul>
      </div>
    );
  }

  return (
    <aside aria-label="Здание" className={isPage ? PAGE_ASIDE : COLUMN_ASIDE}>
      <div className="flex flex-none items-center justify-between gap-[var(--s-3)] px-[var(--s-4)] py-[var(--s-2)]">
        <h2 className={isPage ? 'text-sm font-medium' : 'hidden text-sm font-medium lg:block'}>Здание</h2>
        {!isPage && (
          <Button
            className="min-h-[44px] lg:hidden"
            aria-expanded={open}
            onClick={() => setOpen((value) => !value)}
          >
            {open ? 'Здание (свернуть)' : 'Здание (развернуть)'}
          </Button>
        )}
      </div>
      <div
        className={cx(
          'min-h-0 flex-1 flex-col',
          isPage || open
            ? cx('flex', !isPage && cx('lg:h-auto', groups.length > 1 ? 'h-[272px]' : 'h-[220px]'))
            : 'hidden lg:flex',
        )}
      >
        <CadBuilding3dGroupSelect
          groups={groups}
          value={groupKey ?? ''}
          onChange={(key) => {
            setChosen({ group: key, sheetKey: currentKey });
            setHover(null);
          }}
        />
        {body}
      </div>
    </aside>
  );
};
