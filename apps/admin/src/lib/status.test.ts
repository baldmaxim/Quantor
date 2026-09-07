import { describe, expect, it } from 'vitest';

import { NOT_MEASURED, formatCount, sourceLabel, sourceTone, statusView } from './status';

/**
 * Главное, что здесь проверяется: неизвестное остаётся неизвестным.
 *
 * Панель, показывающая ноль вместо «не знаю», хуже пустой — по ней принимают решения.
 */

describe('состояния проб', () => {
  it('переводит все состояния без пробелов', () => {
    for (const status of [
      'healthy',
      'degraded',
      'unavailable',
      'not_configured',
      'unknown',
    ] as const) {
      const view = statusView(status);
      expect(view.label).toBeTruthy();
      expect(view.tone).toBeTruthy();
    }
  });

  it('не выдаёт неизвестное за исправное', () => {
    expect(statusView('unknown').tone).not.toBe('success');
    expect(statusView('not_configured').tone).not.toBe('success');
    expect(statusView('unknown').label).not.toMatch(/порядк/i);
  });

  it('отличает недоступное от ненастроенного', () => {
    expect(statusView('unavailable').tone).toBe('danger');
    expect(statusView('not_configured').tone).toBe('neutral');
  });
});

describe('счётчики', () => {
  it('неизмеренное показывает прочерком, а не нулём', () => {
    expect(formatCount(undefined)).toBe(NOT_MEASURED);
    expect(formatCount(null)).toBe(NOT_MEASURED);
    expect(formatCount(0)).toBe('0');
  });
});

describe('происхождение значения', () => {
  it('называет каждый уровень по-русски', () => {
    expect(sourceLabel('default')).toBe('умолчание кода');
    expect(sourceLabel('system')).toBe('вся установка');
    expect(sourceLabel('workspace')).toBe('рабочее пространство');
    expect(sourceLabel('deployment')).toBe('окружение');
  });

  it('выделяет аварийный уровень окружения', () => {
    expect(sourceTone('deployment')).toBe('warning');
    expect(sourceTone('default')).toBe('neutral');
  });
});
