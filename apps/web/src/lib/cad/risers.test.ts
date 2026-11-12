import { describe, expect, it } from 'vitest';

import {
  draftOf,
  emptyRiser,
  entryOf,
  hasDetails,
  hasProblems,
  isAirSystem,
  riserProblems,
  systemPatch,
  serializeDrafts,
  type IRiserDraft,
} from './risers';

const filled = (patch: Partial<IRiserDraft> = {}): IRiserDraft => ({
  ...emptyRiser(),
  mark: 'В1.1.1',
  dn: '50',
  source: 'ИОС2.1 л.2',
  ...patch,
});

describe('проверка строки реестра', () => {
  it('верная строка без замечаний', () => {
    expect(hasProblems(riserProblems(filled()))).toBe(false);
    expect(hasProblems(riserProblems(filled({ dn: '', shaftId: 'S123' })))).toBe(false);
  });

  it('марка обязательна и не длиннее 32 знаков', () => {
    expect(riserProblems(filled({ mark: '  ' })).mark).toBeDefined();
    expect(riserProblems(filled({ mark: 'x'.repeat(33) })).mark).toBeDefined();
    expect(riserProblems(filled({ mark: 'x'.repeat(32) })).mark).toBeUndefined();
  });

  it('диаметр - целое 10..400 или пусто', () => {
    for (const dn of ['9', '401', '5.5', 'abc', '-10']) {
      expect(riserProblems(filled({ dn })).dn, dn).toBeDefined();
    }
    for (const dn of ['', '10', '400'])
      expect(riserProblems(filled({ dn })).dn, dn).toBeUndefined();
  });

  it('количество - целое 1..8, шахта - S12 или S123', () => {
    for (const count of ['', '0', '9', '1.5']) {
      expect(riserProblems(filled({ count })).count, count).toBeDefined();
    }
    for (const shaftId of ['S1', 'S1234', 's12', '12']) {
      expect(riserProblems(filled({ shaftId })).shaftId, shaftId).toBeDefined();
    }
    expect(riserProblems(filled({ shaftId: ' S12 ' })).shaftId).toBeUndefined();
  });

  it('источник не длиннее 200 знаков', () => {
    expect(riserProblems(filled({ source: 'x'.repeat(201) })).source).toBeDefined();
  });
});

const air = (patch: Partial<IRiserDraft> = {}): IRiserDraft =>
  filled({ system: 'DU', mark: 'ДУ1', dn: '', sectionA: '400', sectionB: '600', ...patch });

describe('воздушные системы (cad_mep.v10)', () => {
  it('воздушная система: сечение или Ø канала, без Ø трубы', () => {
    expect(isAirSystem('DU')).toBe(true);
    expect(isAirSystem('K1')).toBe(false);
    expect(hasProblems(riserProblems(air()))).toBe(false);
    expect(hasProblems(riserProblems(air({ sectionA: '', sectionB: '' })))).toBe(false);
    expect(riserProblems(air({ dn: '50' })).dn).toBeDefined();
  });

  it('сечение: оба размера целые 50..3000', () => {
    for (const patch of [
      { sectionA: '49' },
      { sectionB: '3001' },
      { sectionB: '' },
      { sectionA: '1.5' },
    ]) {
      expect(riserProblems(air(patch)).section, JSON.stringify(patch)).toBeDefined();
    }
    expect(riserProblems(air({ sectionA: '50', sectionB: '3000' })).section).toBeUndefined();
  });

  it('Ø канала - целое 50..2000', () => {
    const round = (channelD: string) =>
      air({ channelShape: 'round', sectionA: '', sectionB: '', channelD });
    for (const d of ['49', '2001', 'x']) expect(riserProblems(round(d)).channelD, d).toBeDefined();
    for (const d of ['', '50', '2000']) expect(riserProblems(round(d)).channelD, d).toBeUndefined();
  });

  it('у трубной системы канала нет', () => {
    expect(riserProblems(filled({ sectionA: '100', sectionB: '200' })).section).toBeDefined();
    expect(riserProblems(filled({ channelShape: 'round', channelD: '100' })).section).toBeDefined();
  });

  it('этажи: оба целые -10..200, от не больше до', () => {
    const floors = (floorFrom: string, floorTo: string) =>
      riserProblems(filled({ floorFrom, floorTo })).floors;
    for (const [from, to] of [
      ['1', ''],
      ['-11', '3'],
      ['1', '201'],
      ['5', '4'],
      ['a', '2'],
    ]) {
      expect(floors(from as string, to as string), `${from}-${to}`).toBeDefined();
    }
    for (const [from, to] of [
      ['', ''],
      ['-10', '200'],
      ['3', '3'],
    ]) {
      expect(floors(from as string, to as string), `${from}-${to}`).toBeUndefined();
    }
  });

  it('EI не длиннее 16 знаков', () => {
    expect(riserProblems(filled({ ei: 'x'.repeat(17) })).ei).toBeDefined();
    expect(riserProblems(filled({ ei: 'x'.repeat(16) })).ei).toBeUndefined();
  });

  it('запись: сечение, этажи, назначение, клапан, EI; пустые поля не уходят', () => {
    expect(
      entryOf(air({ floorFrom: '2', floorTo: '9', serves: 'stair', valve: 'NO', ei: ' EI60 ' })),
    ).toEqual({
      system: 'DU',
      mark: 'ДУ1',
      dn_mm: null,
      role: 'own',
      count: 1,
      shaft_id: null,
      source: 'ИОС2.1 л.2',
      note: null,
      section_mm: [400, 600],
      floors: [2, 9],
      serves: 'stair',
      valve: 'NO',
      ei: 'EI60',
    });
    const round = entryOf(
      air({ channelShape: 'round', sectionA: '', sectionB: '', channelD: '200' }),
    );
    expect(round.d_mm).toBe(200);
    expect(round).not.toHaveProperty('section_mm');
    expect(entryOf(filled())).not.toHaveProperty('floors');
  });

  it('строка из записи сервера и обратно не меняет содержимое', () => {
    const entry = {
      system: 'VMOP' as const,
      mark: 'ВЕ1',
      dn_mm: null,
      role: 'own' as const,
      count: 1,
      shaft_id: null,
      source: null,
      note: null,
      d_mm: 315,
      floors: [-1, 25] as [number, number],
      serves: 'corridor' as const,
      valve: 'none' as const,
      ei: 'EI30',
    };
    expect(entryOf(draftOf(entry))).toEqual(entry);
    expect(hasDetails(draftOf(entry))).toBe(true);
    expect(hasDetails(filled())).toBe(false);
  });

  it('смена системы между трубной и воздушной очищает чужие поля', () => {
    expect(systemPatch(filled(), 'DU')).toEqual({ system: 'DU', dn: '' });
    expect(systemPatch(air(), 'K1')).toMatchObject({ system: 'K1', sectionA: '', channelD: '' });
    expect(systemPatch(filled(), 'K1')).toEqual({ system: 'K1' });
    expect(systemPatch(air(), 'DP')).toEqual({ system: 'DP' });
  });
});

describe('строка формы и запись контракта', () => {
  it('запись из строки: числа числами, пустое - null, примечание сохраняется', () => {
    const entry = entryOf(
      filled({
        dn: '',
        count: '2',
        shaftId: ' S12 ',
        source: ' ',
        note: 'пара в холле',
        mark: ' Т3 ',
      }),
    );
    expect(entry).toEqual({
      system: 'V1',
      mark: 'Т3',
      dn_mm: null,
      role: 'own',
      count: 2,
      shaft_id: 'S12',
      source: null,
      note: 'пара в холле',
    });
  });

  it('строка из записи сервера и обратно не меняет содержимое', () => {
    const entry = {
      system: 'VPV' as const,
      mark: 'В2.1',
      dn_mm: 65,
      role: 'transit' as const,
      count: 2,
      shaft_id: 'S12',
      source: 'ИОС2.2 л.2',
      note: null,
    };
    expect(entryOf(draftOf(entry))).toEqual(entry);
    expect(draftOf({ system: 'FS', mark: 'В2.6', role: 'own' }).count).toBe('1');
  });

  it('сравнение «изменено» не зависит от служебных ключей и пробелов', () => {
    const a = filled();
    const b = { ...a, key: 'другой', mark: ' В1.1.1 ' };
    expect(serializeDrafts([a])).toBe(serializeDrafts([b]));
    expect(serializeDrafts([a])).not.toBe(serializeDrafts([{ ...a, dn: '65' }]));
  });
});
