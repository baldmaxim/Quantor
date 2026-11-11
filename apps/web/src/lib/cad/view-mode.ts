/**
 * Показ CAD на листе рабочей области: DXF накладывается на подложку PDF («наложение»), а пока
 * DXF показать нельзя - виден один PDF.
 *
 * Подложка PDF и геометрия DXF - два независимых слоя одной камеры. DXF всегда непрозрачный;
 * прозрачность меняется только у PDF, и только в наложении её задаёт ползунок.
 */

export type CadViewMode = 'pdf' | 'overlay';

/** Непрозрачность подложки PDF в наложении по умолчанию. */
export const DEFAULT_PDF_OPACITY = 0.4;
export const MIN_PDF_OPACITY = 0.1;
export const MAX_PDF_OPACITY = 1;

/** Ключ localStorage: непрозрачность PDF в режиме «Наложение». */
export const PDF_OPACITY_KEY = 'quantor.cad.pdf-opacity';

/** Приводит значение к допустимому отрезку; не число - значение по умолчанию. */
export const clampPdfOpacity = (value: number): number =>
  Number.isFinite(value)
    ? Math.min(Math.max(value, MIN_PDF_OPACITY), MAX_PDF_OPACITY)
    : DEFAULT_PDF_OPACITY;

/**
 * Какой режим показан. DXF накладывается на лист только при подтверждённом кадре координат и
 * полученном предпросмотре: без них виден один PDF.
 */
export const resolveCadMode = (dxfAvailable: boolean): CadViewMode =>
  dxfAvailable ? 'overlay' : 'pdf';

export interface ICadRender {
  /** Геометрия DXF рисуется. */
  readonly dxfVisible: boolean;
  /** Непрозрачность холста PDF, 0-1. */
  readonly pdfOpacity: number;
}

/**
 * Что показывать на холсте. Вне вкладки CAD подложка всегда полная (на ней ведут обмер), а DXF
 * виден, пока режим не «PDF». На вкладке CAD: «PDF» - DXF скрыт; «Наложение» - оба, PDF с
 * непрозрачностью ползунка.
 */
export const cadRender = (mode: CadViewMode, sliderOpacity: number, onCadTab: boolean): ICadRender => {
  if (!onCadTab) return { dxfVisible: mode !== 'pdf', pdfOpacity: 1 };
  if (mode === 'pdf') return { dxfVisible: false, pdfOpacity: 1 };
  return { dxfVisible: true, pdfOpacity: clampPdfOpacity(sliderOpacity) };
};
