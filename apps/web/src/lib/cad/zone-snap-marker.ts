import type { ISnapResult } from '@/lib/cad/zone-snap';
import type { ScreenPoint } from '@/lib/viewer/coordinates';

const HALF = 5;
const LINE_WIDTH = 1.5;
const HALO_WIDTH = 3;
const GUIDE_DASH = [4, 4];

export interface ISnapMarkerColors {
  /** Цвет метки (чернила листа). */
  readonly ink: string;
  /** Подложка под меткой (бумага листа): метка читается на любом фоне. */
  readonly paper: string;
}

/**
 * Метка привязки на холсте черновика: вершина - квадрат, ребро - ромб, ortho - тонкая
 * направляющая через опорную вершину и точку. Без привязки (`none`) ничего не рисует.
 */
export const drawSnapMarker = (
  context: CanvasRenderingContext2D,
  colors: ISnapMarkerColors,
  snap: ISnapResult | null,
  at: ScreenPoint,
  anchor: ScreenPoint | null,
  extent: { readonly width: number; readonly height: number },
): void => {
  if (!snap || snap.kind === 'none') return;

  const stroke = (trace: () => void) => {
    for (const [style, width] of [
      [colors.paper, HALO_WIDTH],
      [colors.ink, LINE_WIDTH],
    ] as const) {
      context.strokeStyle = style;
      context.lineWidth = width;
      context.beginPath();
      trace();
      context.stroke();
    }
  };

  if (snap.kind === 'ortho' && anchor) {
    const dx = at.x - anchor.x;
    const dy = at.y - anchor.y;
    const length = Math.hypot(dx, dy);
    if (length === 0) return;
    // Направляющая от опорной вершины через точку до границ холста.
    const reach = (extent.width + extent.height) / length;
    context.setLineDash(GUIDE_DASH);
    context.lineWidth = 1;
    context.strokeStyle = colors.ink;
    context.beginPath();
    context.moveTo(anchor.x - dx * reach, anchor.y - dy * reach);
    context.lineTo(anchor.x + dx * reach, anchor.y + dy * reach);
    context.stroke();
    context.setLineDash([]);
    return;
  }

  if (snap.kind === 'vertex') {
    stroke(() => context.rect(at.x - HALF, at.y - HALF, HALF * 2, HALF * 2));
  } else if (snap.kind === 'edge') {
    stroke(() => {
      context.moveTo(at.x, at.y - HALF);
      context.lineTo(at.x + HALF, at.y);
      context.lineTo(at.x, at.y + HALF);
      context.lineTo(at.x - HALF, at.y);
      context.closePath();
    });
  }
};
