import { CAD_LAYER_PALETTE_SIZE, layerColorToken } from './layer-colors';
import { readMepColors } from './mep-layers';
import type { IRemarkColors } from './remarks-painter';

/** Токены палитры слоёв по порядку; значения читаются из темы. */
const paletteOf = (read: (name: string) => string): string[] =>
  Array.from({ length: CAD_LAYER_PALETTE_SIZE }, (_, slot) => read(layerColorToken(slot)));

/** Цвета слоя - из токенов темы: лист чертежа светлый в обеих темах, чернила не зависят от неё. */
export const readCadPaintColors = () => {
  if (typeof window === 'undefined') {
    return {
      ink: 'CanvasText',
      layers: paletteOf(() => 'CanvasText'),
      paper: 'Canvas',
      crop: 'CanvasText',
      mep: readMepColors(() => 'CanvasText'),
      remarks: { open: 'CanvasText', resolved: 'CanvasText', onOpen: 'Canvas', paper: 'Canvas' },
    };
  }
  const style = getComputedStyle(document.documentElement);
  const token = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback;
  return {
    ink: token('--sheet-ink', 'CanvasText'),
    layers: paletteOf((name) => token(name, 'CanvasText')),
    paper: token('--canvas', 'Canvas'),
    crop: token('--region-stamp', 'CanvasText'),
    mep: readMepColors((name) => token(name, 'CanvasText')),
    // Отметки лежат на светлом листе в обеих темах, поэтому берутся токены чернил листа, а не
    // тематические --danger/--success: те в тёмной теме светлеют и на бумаге не видны.
    // Проверенное отличается от открытого ещё и пунктиром с галочкой.
    remarks: {
      open: token('--sheet-ink-danger', 'CanvasText'),
      resolved: token('--region-image', 'CanvasText'),
      onOpen: token('--region-tag-text', 'Canvas'),
      paper: token('--canvas', 'Canvas'),
    } satisfies IRemarkColors,
  };
};
