import type {
  TenderBaseCandidateRead,
  TenderCalcRead,
  TenderQuantityDiffRead,
  TenderQuantityRowRead,
} from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import { candidateNote, defaultSelection, groupCandidates } from './candidates';
import { formatDelta, formatQty, groupCalcs, tenderSheetHref } from './present';
import { mergeQuantities } from './quantities';
import { DISCIPLINE_LABELS, SYSTEM_LABELS, systemColorToken, systemLabel } from './systems';

const FORMAT_SYSTEMS = [
  'heating',
  'water_supply',
  'sewage',
  'storm_drain',
  'fire_sprinkler',
  'fire_hydrant',
  'dry_pipe',
  'ventilation',
  'smoke_control',
  'conditioning',
  'cooling',
  'itp',
  'mech_other',
  'power',
  'lighting',
  'grounding',
  'lightning',
  'eom_other',
  'ss_network',
  'ss_security',
  'ss_fire_alarm',
  'ss_dispatch',
  'ss_other',
];

describe('словарь систем', () => {
  it('покрывает все коды формата v1 и разделы', () => {
    for (const code of FORMAT_SYSTEMS) expect(SYSTEM_LABELS[code]).toBeTruthy();
    expect(Object.keys(SYSTEM_LABELS)).toHaveLength(FORMAT_SYSTEMS.length);
    expect(DISCIPLINE_LABELS).toEqual({ mech: 'Механика', eom: 'ЭОМ', ss: 'СС' });
    expect(systemLabel('heating')).toBe('Отопление');
    expect(systemLabel('fire_sprinkler')).toBe('АУП');
    expect(systemLabel('power')).toBe('Силовое электрооборудование');
  });

  it('токен цвета: имя переменной, неизвестный код — нейтральный', () => {
    expect(systemColorToken('fire_sprinkler')).toBe('--tender-sys-fire-sprinkler');
    expect(systemColorToken('future_system')).toBe('--cad-mep-node');
    expect(systemLabel('future_system')).toBe('future_system');
  });
});

describe('представление', () => {
  it('числа по-русски, разница со знаком', () => {
    expect(formatQty(1234.5)).toBe(formatQty(1234.5));
    expect(formatQty(null)).toBe('—');
    expect(formatDelta(0)).toBe('0');
    expect(formatDelta(12.5)).toMatch(/^\+12[,.]5$/);
    expect(formatDelta(-3)).toBe('−3');
  });

  it('репозитории по разделам в порядке формата', () => {
    const calc = (id: string, discipline: TenderCalcRead['discipline'], system: string) =>
      ({ id, discipline, system, title: id }) as TenderCalcRead;
    const groups = groupCalcs([
      calc('a', 'ss', 'ss_other'),
      calc('b', 'mech', 'ventilation'),
      calc('c', 'mech', 'heating'),
    ]);
    expect(groups.map((group) => group.discipline)).toEqual(['mech', 'ss']);
    expect(groups[0]?.calcs.map((item) => item.id)).toEqual(['c', 'b']);
  });

  it('ссылка на лист: вид рабочей области + tender=<calc_id>, 3D — отдельным параметром', () => {
    const target = { revisionId: 'rev-1', pageIndex: 81, view: 1, position: 12 };
    const plan = new URL(tenderSheetHref('p-1', 'calc-1', target), 'http://x');
    expect(plan.pathname).toBe('/projects/p-1/workspace');
    expect(plan.searchParams.get('revision')).toBe('rev-1');
    expect(plan.searchParams.get('page')).toBe('12');
    expect(plan.searchParams.get('tab')).toBe('cad');
    expect(plan.searchParams.get('view')).toBe('1');
    expect(plan.searchParams.get('tender')).toBe('calc-1');
    expect(plan.searchParams.get('mode')).toBeNull();
    const volume = new URL(tenderSheetHref('p-1', 'calc-1', target, '3d'), 'http://x');
    expect(volume.searchParams.get('mode')).toBe('3d');
    const fallback = new URL(
      tenderSheetHref('p-1', 'c', { revisionId: 'r', pageIndex: 4, view: 0 }),
      'http://x',
    );
    expect(fallback.searchParams.get('page')).toBe('5');
  });
});

const row = (code: string, qty: number, group: string | null = 'Трубы'): TenderQuantityRowRead => ({
  code,
  name: code,
  unit: 'м',
  qty,
  group,
  basis: 'geometry',
  note: null,
  per_floor: [],
  view_keys: [],
});
const entry = (
  code: string,
  status: TenderQuantityDiffRead['status'],
  qty: number | null,
  qtyPrev: number | null,
): TenderQuantityDiffRead => ({
  code,
  name: code,
  unit: 'м',
  status,
  qty,
  qty_prev: qtyPrev,
  delta: (qty ?? 0) - (qtyPrev ?? 0),
});

describe('объёмы с разницей', () => {
  const rows = [row('A', 10), row('B', 5), row('C', 7, null)];
  const diff = [
    entry('A', 'changed', 10, 8),
    entry('B', 'same', 5, 5),
    entry('C', 'added', 7, null),
    entry('D', 'removed', null, 3),
  ];

  it('склеивает по коду, удалённые — отдельной группой', () => {
    const groups = mergeQuantities(rows, diff, true, false);
    expect(groups.map((group) => group.name)).toEqual([
      'Трубы',
      'Без группы',
      'Удалено относительно прошлой версии',
    ]);
    expect(groups[0]?.rows[0]).toMatchObject({
      code: 'A',
      qtyPrev: 8,
      delta: 2,
      status: 'changed',
    });
    expect(groups[2]?.rows[0]).toMatchObject({ code: 'D', qty: null, status: 'removed' });
  });

  it('«только изменения» прячет строки без разницы', () => {
    const codes = mergeQuantities(rows, diff, true, true).flatMap((group) =>
      group.rows.map((r) => r.code),
    );
    expect(codes).toEqual(['A', 'C', 'D']);
  });

  it('первая версия: без разницы и без подсветки', () => {
    const groups = mergeQuantities(
      rows,
      rows.map((r) => entry(r.code, 'added', r.qty, null)),
      false,
      false,
    );
    const all = groups.flatMap((group) => group.rows);
    expect(all.every((r) => r.status === 'same' && r.delta === null && r.qtyPrev === null)).toBe(
      true,
    );
  });
});

const candidate = (patch: Partial<TenderBaseCandidateRead>): TenderBaseCandidateRead => ({
  alignment: 'reference',
  base_z_mm: 0,
  corps: '9',
  dir: 'd',
  document_id: null,
  document_title: 'АР',
  dxf_sha256: null,
  floors: ['1'],
  group_key: '9|3',
  group_label: 'К9',
  label: 'План 1',
  offset_mm: [0, 0],
  page_index: 0,
  problems: [],
  ready: true,
  revision_id: 'r',
  section: '3',
  view: 0,
  view_key: 'r:0:0',
  ...patch,
});

describe('кандидаты выпуска базы', () => {
  const list = [
    candidate({ view_key: 'a', base_z_mm: 3000, floors: ['2'] }),
    candidate({ view_key: 'b', base_z_mm: 0, floors: ['1'] }),
    candidate({ view_key: 'c', alignment: 'none' }),
    candidate({ view_key: 'd', ready: false, problems: ['кадр вида не подтверждён'] }),
    candidate({ view_key: 'e', corps: null, section: null }),
  ];

  it('дерево корпус → секция, этажи снизу вверх', () => {
    const tree = groupCandidates(list);
    expect(tree.map((corps) => corps.label)).toEqual(['Корпус 9', 'Без корпуса']);
    expect(tree[0]?.sections[0]?.floors.map((floor) => floor.view_key)).toEqual([
      'b',
      'c',
      'd',
      'a',
    ]);
  });

  it('по умолчанию — готовые и совмещённые; пометки у остальных', () => {
    expect([...defaultSelection(list)].sort()).toEqual(['a', 'b', 'e']);
    expect(candidateNote(list[2] as TenderBaseCandidateRead)).toBe('не совмещён с осями здания');
    expect(candidateNote(list[3] as TenderBaseCandidateRead)).toBe('кадр вида не подтверждён');
    expect(candidateNote(list[0] as TenderBaseCandidateRead)).toBeNull();
  });
});
