import type {
  CalcElementProvenance,
  CalcSynthesisStatus,
  CalcSystemNode,
  CalcUnresolvedKind,
} from '@quantor/api-client';

import type { BadgeTone } from '@/components/ui';

/**
 * Подписи синтеза структуры (ADR-0030, PROMPT 05). Граф, происхождение и нерешённое — ответ
 * сервера; экран не выбирает кратность и не рисует трассу.
 */

export const PROVENANCE: Record<CalcElementProvenance, { label: string; tone: BadgeTone }> = {
  OBSERVED: { label: 'наблюдено', tone: 'success' },
  CALCULATED: { label: 'рассчитано', tone: 'accent' },
  SYNTHESIZED: { label: 'синтезировано', tone: 'neutral' },
  ASSUMED: { label: 'допущение', tone: 'warning' },
};

export const SYNTHESIS_STATUS: Record<CalcSynthesisStatus, { label: string; tone: BadgeTone }> = {
  SUCCEEDED: { label: 'построено', tone: 'success' },
  PARTIAL: { label: 'частично', tone: 'accent' },
  BLOCKED: { label: 'заблокировано', tone: 'warning' },
  FAILED: { label: 'ошибка', tone: 'danger' },
};

export const UNRESOLVED_TITLES: Record<CalcUnresolvedKind, string> = {
  COUNT_RANGE: 'количество',
  CHOICE: 'выбор',
  PLACEMENT: 'размещение',
  MISSING_RULE: 'нет правила',
  ROUTE: 'трасса',
};

/** Кратность словами: «4–5», «выбрано 5 из 4–5», «24 раза». Сервер знает, экран называет. */
export const cardinalityText = (node: CalcSystemNode): string => {
  const { min, max, selected } = node.cardinality;
  const count =
    selected != null
      ? `выбрано ${selected} из ${min}–${max}`
      : min === max
        ? `${min}`
        : `${min}–${max}`;
  return node.multiplicity && node.multiplicity > 1 ? `${count} · ×${node.multiplicity}` : count;
};
