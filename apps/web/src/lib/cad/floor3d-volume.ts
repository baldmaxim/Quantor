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
