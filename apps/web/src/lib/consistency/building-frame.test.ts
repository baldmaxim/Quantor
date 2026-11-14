import type { DocQuestionOut } from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import { elevationText, parseHeightMm, parseInteger, parseNumber } from './building-frame';
import { buildManualAnswer, emptyManualForm, manualLayout } from './doc-questions';

describe('каркас здания: форматы и разбор', () => {
  it('отметка со знаком и запятой', () => {
    expect(elevationText(3.3)).toBe('+3,300');
    expect(elevationText(-0.15)).toBe('−0,150');
    expect(elevationText(0)).toBe('±0,000');
    expect(elevationText(null)).toBe('—');
  });

  it('числа формы: пусто — null, мусор — ошибка', () => {
    expect(parseNumber(' 3,3 ')).toEqual({ ok: true, value: 3.3 });
    expect(parseNumber('')).toEqual({ ok: true, value: null });
    expect(parseNumber('abc')).toEqual({ ok: false });
    expect(parseInteger('-1')).toEqual({ ok: true, value: -1 });
    expect(parseInteger('2.5')).toEqual({ ok: false });
    expect(parseHeightMm('3300')).toEqual({ ok: true, value: 3.3 });
    expect(parseHeightMm('0')).toEqual({ ok: false });
  });
});

describe('ручной ответ-количество (этажность)', () => {
  const question: Pick<DocQuestionOut, 'code' | 'value_kind' | 'min_mm' | 'max_mm' | 'options'> = {
    code: 'storeys',
    value_kind: 'count',
    min_mm: 1,
    max_mm: 150,
    options: [],
  };

  it('одно целое число без единицы мм', () => {
    const layout = manualLayout(question);
    expect(layout.numberLabels).toEqual(['Количество, шт.']);
    const form = { ...emptyManualForm(layout), numbers: ['25'], note: 'ПЗ, стр. 3' };
    expect(buildManualAnswer(question, form)).toEqual({
      body: {
        source: 'manual',
        value_text: '25',
        value: { numbers: [25], qualifier: null, code: null },
        note: 'ПЗ, стр. 3',
      },
    });
  });

  it('вне границ каталога — ошибка без «мм»', () => {
    const layout = manualLayout(question);
    const form = { ...emptyManualForm(layout), numbers: ['400'], note: 'ПЗ' };
    expect(buildManualAnswer(question, form)).toEqual({
      error: 'Число 400 вне допустимых 1–150.',
    });
  });
});
