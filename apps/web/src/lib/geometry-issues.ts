import type { GeometryIssueCode } from '@quantor/api-client';

/**
 * Что не так с контуром — словами для человека (ADR-0026).
 *
 * Сервер отдаёт код дефекта: и в отказе записи `GEOMETRY_INVALID`, и в величине строки, попавшей
 * в базу до политики. Текст один на оба места, иначе одна и та же фигура объяснялась бы по-разному.
 */
export const GEOMETRY_ISSUE_LABELS: Readonly<Record<GeometryIssueCode, string>> = {
  too_few_vertices: 'в контуре меньше трёх вершин',
  duplicate_vertex: 'две вершины подряд совпадают',
  degenerate_ring: 'контур вырожден в линию',
  self_intersection: 'рёбра контура пересекаются или касаются',
  ring_intersection: 'отверстие пересекает или касается другого контура',
  hole_outside_outer: 'отверстие лежит вне контура',
  hole_inside_hole: 'отверстие лежит внутри другого отверстия',
  too_complex: 'контур слишком сложен для проверки',
};

const isIssueCode = (value: unknown): value is GeometryIssueCode =>
  typeof value === 'string' && value in GEOMETRY_ISSUE_LABELS;

/** Код дефекта из тела ошибки API или `null`, если его там нет. */
export const geometryIssueOf = (error: unknown): GeometryIssueCode | null => {
  if (typeof error !== 'object' || error === null || !('detail' in error)) return null;
  const code = (error as { detail?: { issue?: { code?: unknown } } }).detail?.issue?.code;
  return isIssueCode(code) ? code : null;
};
