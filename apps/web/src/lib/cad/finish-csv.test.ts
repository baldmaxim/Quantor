import { describe, expect, it } from 'vitest';

import {
  finishZoneFixture,
  sheetFixture,
  templateFixture,
  wallsBreakdownFixture,
} from '@/components/cad/finishes/finish-fixtures';

import { CSV_BOM, buildFinishCsv, finishCsvFilename } from './finish-csv';
import { WALLS_UNLINKED_LABEL } from './finish-sheet';

const lines = (csv: string): string[] => csv.replace(CSV_BOM, '').split('\r\n');

describe('CSV ведомости отделки', () => {
  it('UTF-8 с BOM, разделитель «;», запятая в десятичных', () => {
    const csv = buildFinishCsv(sheetFixture(), [templateFixture()]);
    expect(csv.startsWith(CSV_BOM)).toBe(true);
    const rows = lines(csv);
    expect(rows[0]).toContain('Зона;Тип помещения;Шаблон');
    expect(rows[1]).toBe(
      'Коридор;Коридор;Черновая МОП;по типу;12,5;37,8;12,5;2700;уровни листа;по конструкциям;6,5;17,55;4;10,8;1,5;4,05;2;0,9;0,8;0,3;3,6;0,54;Пол;Стяжка;Смесь М150;1;50;;12,5;1125;кг',
    );
  });

  it('колонки разбивки стен и основания слоя', () => {
    const header = lines(buildFinishCsv(sheetFixture(), []))[0]?.split(';') ?? [];
    expect(header).toEqual(
      expect.arrayContaining([
        'Привязка стен',
        'Монолит, м',
        'Монолит, м2',
        'Кладка, м',
        'ГКЛ, м2',
        'Двери над проёмами, м2',
        'Проёмы без двери, м',
        'Без стены, м',
        'Откосы, м2',
        'Основания',
      ]),
    );
    const zone = finishZoneFixture({
      layers: [
        {
          surface: 'walls',
          work: 'Штукатурка',
          material: null,
          coats: 1,
          thickness_mm: null,
          bases: ['monolith', 'masonry'],
          area_m2: 28.35,
          material_qty: null,
          material_unit: null,
        },
      ],
    });
    const row = lines(buildFinishCsv(sheetFixture({ zones: [zone] }), []))[1] ?? '';
    expect(row).toContain(';Стены;Штукатурка;;1;;Монолит, Кладка;28,35;;');
  });

  it('итоги по слоям и по типам помещений идут после зон', () => {
    const rows = lines(buildFinishCsv(sheetFixture(), [templateFixture()]));
    const totals = rows.indexOf('Итого по слоям');
    const types = rows.indexOf('Итого по типам помещений');
    expect(totals).toBeGreaterThan(1);
    expect(rows[totals + 2]).toBe('Пол;Стяжка;Смесь М150;12,5;1125;кг;1');
    expect(types).toBeGreaterThan(totals);
    expect(rows[types + 2]).toBe('Коридор;1;12,5;37,8;12,5');
  });

  it('не определено - пустая ячейка, не 0; зона без слоёв - одна строка', () => {
    const zone = finishZoneFixture({
      template_id: null,
      template_source: null,
      floor_area_m2: null,
      wall_area_m2: null,
      ceiling_area_m2: null,
      wall_height_mm: null,
      wall_height_source: null,
      walls_breakdown: wallsBreakdownFixture({
        linked: false,
        monolith_m: null,
        masonry_m: null,
        gkl_m: null,
        door_m: null,
        gap_m: null,
        open_m: null,
        area_by_base: { monolith: null, masonry: null, gkl: null },
        door_over_area_m2: null,
        reveal_m: null,
        reveal_area_m2: null,
      }),
      layers: [],
    });
    const rows = lines(
      buildFinishCsv(sheetFixture({ zones: [zone], totals: [], by_room_type: [] }), []),
    );
    // 9 ячеек головы зоны, привязка, 12 пустых величин разбивки и 9 пустых колонок слоя
    expect(rows[1]).toBe(
      [
        'Коридор',
        'Коридор',
        ...Array<string>(7).fill(''),
        WALLS_UNLINKED_LABEL,
        ...Array<string>(21).fill(''),
      ].join(';'),
    );
  });

  it('текст с «;» и кавычками экранируется, формулы Excel обезврежены', () => {
    const zone = finishZoneFixture({
      name: 'A;B "C"',
      layers: [
        {
          surface: 'walls',
          work: '=SUM(A1)',
          material: null,
          coats: 2,
          thickness_mm: null,
          bases: null,
          area_m2: null,
          material_qty: null,
          material_unit: null,
        },
      ],
    });
    const rows = lines(buildFinishCsv(sheetFixture({ zones: [zone] }), []));
    expect(rows[1]?.startsWith('"A;B ""C""";')).toBe(true);
    expect(rows[1]).toContain(";Стены;'=SUM(A1);;2;;;;;");
  });

  it('имя файла - номер страницы с 1', () => {
    expect(finishCsvFilename(81)).toBe('otdelka-list-82.csv');
  });
});
