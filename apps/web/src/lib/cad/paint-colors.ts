import type { IRemarkColors } from './remarks-painter';

/** Цвета слоя - из токенов темы: лист чертежа светлый в обеих темах, чернила не зависят от неё. */
export const readCadPaintColors = () => {
  if (typeof window === 'undefined') {
    return {
      ink: 'CanvasText',
      paper: 'Canvas',
      crop: 'CanvasText',
      remarks: { open: 'CanvasText', resolved: 'CanvasText', onOpen: 'Canvas', paper: 'Canvas' },
    };
  }
  const style = getComputedStyle(document.documentElement);
  const token = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback;
  return {
    ink: token('--sheet-ink', 'CanvasText'),
    paper: token('--canvas', 'Canvas'),
    crop: token('--region-stamp', 'CanvasText'),
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
