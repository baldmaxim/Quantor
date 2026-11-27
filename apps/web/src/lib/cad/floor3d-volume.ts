import type { CadConstructionRead, CadConstructionsRead } from '@quantor/api-client';

/**
 * Величины стены для плашки 3D-вида (ADR-0039). Источник - ответ конструкций листа
 * (`useCadConstructions`, ключ запроса общий с вкладкой «Конструкции»); вид ничего не считает.
 * Сопоставление - по `construction_key` стены 3D-модели = `id` конструкции.
 */

export interface IWallQuantities {
  readonly lengthM: number | null;
  readonly heightMm: number | null;
  readonly wallAreaM2: number | null;
  readonly volumeM3: number | null;
  readonly thicknessNominalMm: number | null;
  /** `true` - человек принял конструкцию; иначе её нужно проверить. */
  readonly accepted: boolean;
}

/** Конструкция по ключу; нет ответа или ключа - `null`. */
export const findConstruction = (
  data: Pick<CadConstructionsRead, 'constructions'> | null | undefined,
  key: string,
): CadConstructionRead | null => data?.constructions.find((item) => item.id === key) ?? null;

export interface ISlabTotals {
  readonly areaM2: number | null;
  readonly thicknessMm: number | null;
  readonly volumeM3: number | null;
}

const sumOrNull = (values: readonly (number | null | undefined)[]): number | null =>
  values.some((value) => value === null || value === undefined)
    ? null
    : values.reduce<number>((sum, value) => sum + (value as number), 0);

/**
 * Плита листа: сумма величин всех её частей (`slab`, `slab-2`... - лист из двух корпусов); `null` -
 * плиты среди конструкций нет. Часть без величины даёт «не определено», а не заниженную сумму.
 */
export const slabTotals = (
  data: Pick<CadConstructionsRead, 'constructions'> | null | undefined,
): ISlabTotals | null => {
  const parts = data?.constructions.filter((item) => item.kind === 'floor_slab') ?? [];
  if (parts.length === 0) return null;
  const main = parts.find((item) => item.id === 'slab') ?? parts[0]!;
  return {
    areaM2: sumOrNull(parts.map((item) => item.computed.area_m2)),
    thicknessMm: main.computed.thickness_mm ?? null,
    volumeM3: sumOrNull(parts.map((item) => item.computed.volume_m3)),
  };
};

/** Величины стены; `null` - данных по этому ключу нет (объём «не определён», а не 0). */
export const wallQuantities = (
  data: Pick<CadConstructionsRead, 'constructions'> | null | undefined,
  key: string,
): IWallQuantities | null => {
  const item = findConstruction(data, key);
  if (item === null) return null;
  return {
    lengthM: item.computed.length_m,
    heightMm: item.computed.height_mm,
    wallAreaM2: item.computed.wall_area_m2,
    volumeM3: item.computed.volume_m3,
    thicknessNominalMm: item.thickness_nominal_mm,
    accepted: item.accepted,
  };
};
