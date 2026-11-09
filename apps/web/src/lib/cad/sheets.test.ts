import type { ScaleCalibrationRead } from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import { cadErrorText } from './errors';
import {
  MAX_CAD_PAGES,
  calibrationPagesOf,
  canLaunchCad,
  hasDefaultCalibration,
  missingCalibrationPages,
  sheetWorkspaceHref,
  toggleSheetPage,
  type SheetCalibrationState,
} from './sheets';

const states = (entries: [number, SheetCalibrationState][]) => new Map(entries);
const calibration = (isDefault: boolean) => ({ is_default: isDefault }) as ScaleCalibrationRead;

describe('выбор листов', () => {
  it('по умолчанию ничего не выбрано - запуск закрыт', () => {
    expect(canLaunchCad([], states([[0, 'calibrated']]))).toBe(false);
  });

  it('выбор добавляется, снимается и остаётся упорядоченным', () => {
    expect(toggleSheetPage([], 3)).toEqual([3]);
    expect(toggleSheetPage([3], 1)).toEqual([1, 3]);
    expect(toggleSheetPage([1, 3], 3)).toEqual([1]);
  });

  it('больше 50 листов выбрать нельзя, снять можно', () => {
    const full = Array.from({ length: MAX_CAD_PAGES }, (_, index) => index);
    expect(toggleSheetPage(full, 99)).toEqual(full);
    expect(toggleSheetPage(full, 0)).toHaveLength(MAX_CAD_PAGES - 1);
  });

  it('действующая калибровка - только is_default', () => {
    expect(hasDefaultCalibration([calibration(false)])).toBe(false);
    expect(hasDefaultCalibration([calibration(false), calibration(true)])).toBe(true);
    expect(hasDefaultCalibration([])).toBe(false);
  });

  it('лист без калибровки блокирует запуск, откалиброванные - нет', () => {
    const map = states([
      [0, 'calibrated'],
      [1, 'missing'],
    ]);
    expect(canLaunchCad([0], map)).toBe(true);
    expect(canLaunchCad([0, 1], map)).toBe(false);
    expect(missingCalibrationPages([0, 1], map)).toEqual([1]);
  });

  it('пока калибровка проверяется, запуск закрыт; неизвестный статус решает сервер', () => {
    expect(canLaunchCad([0], states([[0, 'loading']]))).toBe(false);
    expect(canLaunchCad([0], states([[0, 'unknown']]))).toBe(true);
  });

  it('ссылка на лист ведёт в рабочую область с номером с 1', () => {
    expect(sheetWorkspaceHref('p', 'r', 2)).toBe('/projects/p/workspace?revision=r&page=3');
  });
});

describe('отказ 409 CAD_CALIBRATION_REQUIRED', () => {
  const conflict = {
    detail: { code: 'CAD_CALIBRATION_REQUIRED', issue: { pages: '0,4' } },
  };

  it('страницы читаются из issue.pages', () => {
    expect(calibrationPagesOf(conflict)).toEqual([0, 4]);
    expect(calibrationPagesOf({ error: conflict })).toEqual([0, 4]);
    expect(calibrationPagesOf({ detail: { code: 'X' } })).toEqual([]);
  });

  it('текст называет страницы с 1', () => {
    expect(cadErrorText(conflict)).toContain('стр. 1, 5');
  });

  it('без списка страниц текст общий', () => {
    expect(cadErrorText({ detail: { code: 'CAD_CALIBRATION_REQUIRED' } })).toContain(
      'Откалибруйте',
    );
  });
});
