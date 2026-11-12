/**
 * Рисовальщик разметки разрезов поверх листа (Canvas2D, ADR-0015, ADR-0025).
 *
 * Рамки приходят от генератора в долях отображаемой страницы (поворот уже учтён, ADR-0008), поэтому
 * кладутся на лист как есть. Статус уровня виден не только цветом: у отклонённого штрих пунктирный
 * и заливка слабее. Цвета - токены чернил листа: лист светлый в обеих темах.
 */

import type { SectionIssueRead, SectionLevelRead } from '@quantor/api-client';

import { toScreenRect, type NormalizedRect, type SheetPlacement } from '@/lib/viewer/coordinates';
import { beginLayerPaint, boundsIntersectAny, visibleRects } from '@/lib/viewer/layer-paint';
import type { LayerPainter } from '@/lib/viewer/viewport-layer';

import { beginOverPaint } from './remarks-painter';
import type { SectionLevelStatus } from './sections';

export interface ISectionColors {
  readonly accepted: string;
  readonly candidate: string;
  readonly rejected: string;
  readonly danger: string;
}

export interface ISectionPaintData {
  /** Уровни показанной страницы. */
  readonly levels: readonly SectionLevelRead[];
  /** Замечания генератора со своей рамкой. */
  readonly issues: readonly Pick<SectionIssueRead, 'bbox'>[];
  readonly colors: ISectionColors;
  /** Выбранный уровень: рисуется толще. */
  readonly activeId: string | null;
}

/** Цвета по токенам чернил листа (вне темы): принят - зелёный, кандидат - синий, отклонён - серый. */
export const readSectionColors = (): ISectionColors => {
  if (typeof window === 'undefined') {
    return { accepted: 'CanvasText', candidate: 'CanvasText', rejected: 'CanvasText', danger: 'CanvasText' };
  }
  const style = getComputedStyle(document.documentElement);
  const token = (name: string) => style.getPropertyValue(name).trim() || 'CanvasText';
  return {
    accepted: token('--cad-layer-3'),
    candidate: token('--sheet-ink'),
    rejected: token('--cad-mep-node'),
    danger: token('--sheet-ink-danger'),
  };
};

/** Цвет уровня по статусу. */
export const levelColor = (colors: ISectionColors, status: SectionLevelStatus): string =>
  colors[status];

/** Прозрачность заливки полосы: принятое заметнее кандидата, отклонённое почти не закрашено. */
export const bandAlpha = (status: SectionLevelStatus): number =>
  status === 'accepted' ? 0.18 : status === 'candidate' ? 0.1 : 0.04;

const LINE_WIDTH = 1.5;
const ACTIVE_LINE_WIDTH = 3.5;
const REJECTED_DASH = [5, 4];
const STRUCTURE_DASH = [6, 3];
const OTHER_DASH = [2, 3];
/** Запас отсечения на толщину штриха. */
const MARGIN = 12;

interface IBox {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

/** Рамка на экране; поворот вида, который выбрал человек, учитывает `toScreenRect`. */
const boxOf = (rect: NormalizedRect, placement: SheetPlacement): IBox =>
  toScreenRect(rect, placement);

const hits = (box: IBox, rects: readonly IBox[]): boolean =>
  boundsIntersectAny(box.x, box.y, box.x + box.width, box.y + box.height, rects);

/** Все рамки данных в порядке, нужном и рисованию, и вопросу «есть ли что рисовать». */
const boxesOf = (data: ISectionPaintData, placement: SheetPlacement): IBox[] => [
  ...data.levels.flatMap((level) => [
    boxOf(level.markup.band, placement),
    boxOf(level.markup.upper_mark, placement),
    boxOf(level.markup.lower_mark, placement),
    ...level.markup.dims.map((dim) => boxOf(dim.bbox, placement)),
  ]),
  ...data.issues.flatMap((issue) => (issue.bbox ? [boxOf(issue.bbox, placement)] : [])),
];

const stroke = (
  context: CanvasRenderingContext2D,
  box: IBox,
  color: string,
  width: number,
  dash: readonly number[],
): void => {
  context.strokeStyle = color;
  context.lineWidth = width;
  context.setLineDash([...dash]);
  context.strokeRect(box.x, box.y, box.width, box.height);
};

const drawLevel = (
  context: CanvasRenderingContext2D,
  level: SectionLevelRead,
  placement: SheetPlacement,
  data: ISectionPaintData,
  rects: readonly IBox[],
): void => {
  const color = levelColor(data.colors, level.status);
  const width = level.id === data.activeId ? ACTIVE_LINE_WIDTH : LINE_WIDTH;
  const dash = level.status === 'rejected' ? REJECTED_DASH : [];
  const draw = (rect: NormalizedRect, action: (box: IBox) => void) => {
    const box = boxOf(rect, placement);
    if (hits(box, rects)) action(box);
  };

  draw(level.markup.band, (box) => {
    context.globalAlpha = bandAlpha(level.status);
    context.fillStyle = color;
    context.fillRect(box.x, box.y, box.width, box.height);
    context.globalAlpha = 1;
    stroke(context, box, color, width, dash);
  });
  draw(level.markup.upper_mark, (box) => stroke(context, box, color, width, dash));
  draw(level.markup.lower_mark, (box) => stroke(context, box, color, width, dash));
  for (const dim of level.markup.dims) {
    const style = dim.role === 'clear' ? [] : dim.role === 'structure' ? STRUCTURE_DASH : OTHER_DASH;
    draw(dim.bbox, (box) => stroke(context, box, color, width, style));
  }
};

/**
 * Рисовальщик разметки разрезов. `clear: true` - слой только с разметкой (чистит холст сам);
 * `false` - поверх другого рисовальщика того же слоя (см. `composePainters`).
 */
export const createSectionsPainter = (
  data: ISectionPaintData,
  options: { readonly clear: boolean },
): LayerPainter => ({
  paint: (context, placement, ratio, area) => {
    const rects = options.clear
      ? beginLayerPaint(context, ratio, area, MARGIN)
      : beginOverPaint(context, ratio, area);
    // Выбранный уровень рисуется последним: его рамки не перекрываются соседними.
    const levels = [...data.levels].sort(
      (a, b) => Number(a.id === data.activeId) - Number(b.id === data.activeId),
    );
    for (const level of levels) drawLevel(context, level, placement, data, rects);
    for (const issue of data.issues) {
      if (!issue.bbox) continue;
      const box = boxOf(issue.bbox, placement);
      if (hits(box, rects)) stroke(context, box, data.colors.danger, LINE_WIDTH + 0.5, []);
    }
    context.setLineDash([]);
    context.globalAlpha = 1;
    context.restore();
  },

  touches: (placement, ratio, area) => {
    const rects = visibleRects(area, ratio, MARGIN);
    return boxesOf(data, placement).some((box) => hits(box, rects));
  },
});
