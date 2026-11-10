/**
 * Цвета слоёв DXF.
 *
 * Палитра - CSS-токены `--cad-layer-1…N` (packages/ui/src/base.css), своя для каждой темы.
 * Слою цвет назначается по порядку слоя в предпросмотре: соседние слои всегда разного цвета,
 * а один и тот же предпросмотр красится одинаково и на холсте, и в списке слоёв.
 */

/** Сколько цветов в палитре (число токенов `--cad-layer-N`). */
export const CAD_LAYER_PALETTE_SIZE = 12;

/** Номер цвета палитры (с нуля) для слоя с индексом `layerIndex`. */
export const layerColorSlot = (layerIndex: number): number => {
  const index = Number.isFinite(layerIndex) ? Math.trunc(layerIndex) : 0;
  return ((index % CAD_LAYER_PALETTE_SIZE) + CAD_LAYER_PALETTE_SIZE) % CAD_LAYER_PALETTE_SIZE;
};

/** Имя токена цвета слоя без `var()`: `--cad-layer-3`. */
export const layerColorToken = (layerIndex: number): string =>
  `--cad-layer-${layerColorSlot(layerIndex) + 1}`;

/** Значение для `style`/`background`: следует за темой без перерисовки холста. */
export const layerColorVar = (layerIndex: number): string => `var(${layerColorToken(layerIndex)})`;

/**
 * Цвета слоёв для холста (Canvas2D не понимает `var()`): `palette` - разобранные значения
 * токенов по порядку, результат - цвет каждого из `count` слоёв.
 */
export const assignLayerColors = (palette: readonly string[], count: number): string[] => {
  if (palette.length === 0) return [];
  return Array.from(
    { length: Math.max(0, count) },
    (_, index) => palette[layerColorSlot(index) % palette.length] ?? '',
  );
};
