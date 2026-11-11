import { describe, expect, it } from 'vitest';

import {
  draftOf,
  emptyRiser,
  entryOf,
  hasProblems,
  riserProblems,
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
