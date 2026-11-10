import { describe, expect, it } from 'vitest';

import {
  DEFAULT_PDF_OPACITY,
  MAX_PDF_OPACITY,
  MIN_PDF_OPACITY,
  cadRender,
  clampPdfOpacity,
  resolveCadMode,
} from './view-mode';

describe('непрозрачность PDF', () => {
  it('по умолчанию 40 %', () => {
    expect(DEFAULT_PDF_OPACITY).toBe(0.4);
  });

  it('значение зажимается в допустимый отрезок; не число - по умолчанию', () => {
    expect(clampPdfOpacity(0)).toBe(MIN_PDF_OPACITY);
    expect(clampPdfOpacity(5)).toBe(MAX_PDF_OPACITY);
    expect(clampPdfOpacity(0.55)).toBe(0.55);
    expect(clampPdfOpacity(Number.NaN)).toBe(DEFAULT_PDF_OPACITY);
  });
});

describe('режим показа', () => {
  it('DXF можно показать - выбранный режим сохраняется', () => {
    expect(resolveCadMode('overlay', true)).toBe('overlay');
    expect(resolveCadMode('cad', true)).toBe('cad');
    expect(resolveCadMode('pdf', true)).toBe('pdf');
  });

  it('DXF показать нельзя - только PDF', () => {
    expect(resolveCadMode('overlay', false)).toBe('pdf');
    expect(resolveCadMode('cad', false)).toBe('pdf');
  });
});

describe('что рисуется на холсте', () => {
  it('вкладка CAD, «PDF»: подложка целиком, DXF скрыт', () => {
    expect(cadRender('pdf', 0.4, true)).toEqual({ dxfVisible: false, pdfOpacity: 1 });
  });

  it('вкладка CAD, «CAD»: подложка скрыта независимо от ползунка, DXF виден', () => {
    expect(cadRender('cad', 0.4, true)).toEqual({ dxfVisible: true, pdfOpacity: 0 });
    expect(cadRender('cad', 1, true)).toEqual({ dxfVisible: true, pdfOpacity: 0 });
  });

  it('вкладка CAD, «Наложение»: подложка с непрозрачностью ползунка, DXF виден', () => {
    expect(cadRender('overlay', 0.4, true)).toEqual({ dxfVisible: true, pdfOpacity: 0.4 });
    expect(cadRender('overlay', 0.75, true)).toEqual({ dxfVisible: true, pdfOpacity: 0.75 });
  });

  it('другие вкладки: подложка всегда целиком (на ней ведут обмер), DXF по режиму', () => {
    expect(cadRender('overlay', 0.2, false)).toEqual({ dxfVisible: true, pdfOpacity: 1 });
    expect(cadRender('cad', 0.2, false)).toEqual({ dxfVisible: true, pdfOpacity: 1 });
    expect(cadRender('pdf', 0.2, false)).toEqual({ dxfVisible: false, pdfOpacity: 1 });
  });
});
