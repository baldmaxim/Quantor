import { describe, expect, it } from 'vitest';

import {
  finishZoneFixture,
  sheetFixture,
  templateFixture,
} from '@/components/cad/finishes/finish-fixtures';

import { buildFinishSteps } from './finish-steps';

describe('шаги раздела «Отделка»', () => {
  it('ничего не загружено: все шаги нейтральны, числа - «—», не 0', () => {
    const steps = buildFinishSteps(undefined, undefined);
    for (const step of [steps.zones, steps.templates, steps.assignment, steps.sheet]) {
      expect(step.status).toBe('neutral');
      expect(step.summary).toContain('—');
      expect(step.summary).not.toContain('0');
      expect(step.hint).toBeNull();
    }
    expect(steps.calibration).toBeNull();
    expect(steps.templates.collapsed).toBe(false);
  });

  it('всё готово: четыре «готово», шаблоны свёрнуты', () => {
    const steps = buildFinishSteps(sheetFixture(), [templateFixture()]);
    expect(steps.zones).toMatchObject({
      status: 'ready',
      summary: 'Помещений на листе: 1 · без типа: 0',
    });
    expect(steps.templates).toMatchObject({
      status: 'ready',
      summary: 'Шаблонов: 1',
      collapsed: true,
    });
    expect(steps.assignment).toMatchObject({
      status: 'ready',
      summary: 'С шаблоном: 1 из 1 (по типу: 1, явно: 0)',
    });
    expect(steps.sheet.status).toBe('ready');
  });

  it('нет зон: шаг 1 требует разметки, шаг 3 недоступен, ведомость не готова', () => {
    const steps = buildFinishSteps(sheetFixture({ zones: [], totals: [], by_room_type: [] }), [
      templateFixture(),
    ]);
    expect(steps.zones.status).toBe('action');
    expect(steps.zones.hint).toContain('нет зон-помещений');
    expect(steps.assignment.status).toBe('neutral');
    expect(steps.assignment.summary).toBe('С шаблоном: —');
    expect(steps.sheet.status).toBe('action');
  });

  it('зоны без типа и без шаблона попадают в списки шагов 1 и 3', () => {
    const sheet = sheetFixture({
      zones: [
        finishZoneFixture({ zone_id: 'a' }),
        finishZoneFixture({ zone_id: 'b', template_source: 'explicit' }),
        finishZoneFixture({
          zone_id: 'c',
          room_type: null,
          template_id: null,
          template_source: null,
        }),
      ],
      warnings: [{ code: 'no_template', zone_ids: ['c'] }],
    });
    const steps = buildFinishSteps(sheet, [templateFixture()]);
    expect(steps.zones).toMatchObject({
      status: 'action',
      summary: 'Помещений на листе: 3 · без типа: 1',
      untypedIds: ['c'],
    });
    expect(steps.assignment).toMatchObject({
      status: 'action',
      summary: 'С шаблоном: 2 из 3 (по типу: 1, явно: 1)',
      withoutTemplateIds: ['c'],
    });
    // Тип не задан - непокрытых типов нет: шаблоны готовы.
    expect(steps.templates.status).toBe('ready');
    // no_template переехал в шаг 3 и блокирует ведомость.
    expect(steps.sheet.warnings).toEqual([]);
    expect(steps.sheet.status).toBe('action');
  });

  it('шаблонов нет / тип зоны не покрыт шаблоном', () => {
    const zone = finishZoneFixture({
      room_type: 'kitchen',
      template_id: null,
      template_source: null,
    });
    const sheet = sheetFixture({ zones: [zone] });
    const none = buildFinishSteps(sheet, []);
    expect(none.templates).toMatchObject({ status: 'action', summary: 'Шаблонов: 0' });
    expect(none.templates.hint).toContain('Создайте шаблон');

    const uncovered = buildFinishSteps(sheet, [templateFixture({ room_types: ['corridor'] })]);
    expect(uncovered.templates).toMatchObject({
      status: 'action',
      uncoveredTypes: ['kitchen'],
      hint: 'Нет шаблона для типов: Кухня',
      collapsed: false,
    });
  });

  it('зона с явным шаблоном не требует шаблона для своего типа', () => {
    const sheet = sheetFixture({
      zones: [finishZoneFixture({ room_type: 'kitchen', template_source: 'explicit' })],
    });
    expect(buildFinishSteps(sheet, [templateFixture()]).templates.status).toBe('ready');
  });

  it('шаблоны загружены, ведомость нет: покрытие типов неизвестно - шаг нейтрален', () => {
    const steps = buildFinishSteps(undefined, [templateFixture()]);
    expect(steps.templates).toMatchObject({ status: 'neutral', summary: 'Шаблонов: 1' });
  });

  it('квартиры без отделки не требуют ни типа, ни шаблона', () => {
    const sheet = sheetFixture({
      zones: [
        finishZoneFixture({ zone_id: 'a' }),
        finishZoneFixture({
          zone_id: 'q',
          kind: 'room_apartment',
          room_type: null,
          template_id: null,
          template_source: null,
        }),
      ],
      warnings: [{ code: 'apartment_without_finish', zone_ids: ['q'] }],
    });
    const steps = buildFinishSteps(sheet, [templateFixture()]);
    expect(steps.zones).toMatchObject({
      status: 'ready',
      summary: 'Помещений на листе: 2 · без типа: 0 · без отделки: 1',
    });
    expect(steps.assignment).toMatchObject({
      status: 'ready',
      summary: 'С шаблоном: 1 из 1 (по типу: 1, явно: 0)',
    });
    expect(steps.sheet.warnings.map((w) => w.code)).toEqual(['apartment_without_finish']);
    expect(steps.sheet.status).toBe('ready');
  });

  it('разбор предупреждений: калибровка - в плашку, высота стен блокирует шаг 4', () => {
    const sheet = sheetFixture({
      warnings: [
        { code: 'calibration_missing', zone_ids: ['z1'] },
        { code: 'wall_height_missing', zone_ids: ['z1'] },
        { code: 'windows_not_detected', zone_ids: [] },
      ],
    });
    const steps = buildFinishSteps(sheet, [templateFixture()]);
    expect(steps.calibration).toEqual({ code: 'calibration_missing', zone_ids: ['z1'] });
    expect(steps.sheet.warnings.map((w) => w.code)).toEqual([
      'wall_height_missing',
      'windows_not_detected',
    ]);
    expect(steps.sheet.status).toBe('action');

    const soft = buildFinishSteps(
      sheetFixture({ warnings: [{ code: 'windows_not_detected', zone_ids: [] }] }),
      [templateFixture()],
    );
    expect(soft.sheet.status).toBe('ready');
  });

  it('итогов нет без блокирующих предупреждений: ведомость не готова', () => {
    const steps = buildFinishSteps(sheetFixture({ totals: [] }), [templateFixture()]);
    expect(steps.sheet.status).toBe('action');
    expect(steps.sheet.hint).toContain('Количеств пока нет');
  });
});
