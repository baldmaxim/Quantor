import type { CadBuilding3dFloorRead, CadBuilding3dGroupRead } from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import { sourceFloorsOf, targetFloorsOf } from './site-pin-floors';

const floor = (patch: Partial<CadBuilding3dFloorRead>): CadBuilding3dFloorRead =>
  ({
    job_id: 'j',
    revision_id: 'r',
    page_index: 0,
    view: 0,
    label: '1 этаж',
    group_key: 'k1',
    group_label: 'К1',
    base_z_mm: 0,
    outline: [[0, 0], [10000, 0], [10000, 5000], [0, 5000]],
    walls: [],
    ...patch,
  }) as CadBuilding3dFloorRead;

const group = (key: string, placement: CadBuilding3dGroupRead['placement']): CadBuilding3dGroupRead =>
  ({ key, label: key.toUpperCase(), placement }) as CadBuilding3dGroupRead;

describe('этажи диалога привязки', () => {
  it('корпус: этажи группы с геометрией снизу вверх, копии одного листа не повторяются', () => {
    const floors = [
      floor({ job_id: 'a', page_index: 2, base_z_mm: 3000, label: '2 этаж' }),
      floor({ job_id: 'b', page_index: 1, base_z_mm: 0 }),
      floor({ job_id: 'c', page_index: 2, base_z_mm: 6000, label: '3 этаж', typical_of: 'x' }),
      floor({ job_id: 'd', page_index: 5, outline: [], walls: null, base_z_mm: -3000 }),
      floor({ job_id: 'e', group_key: 'k2', page_index: 9 }),
    ];
    expect(sourceFloorsOf(floors, 'k1').map((item) => item.job_id)).toEqual(['b', 'a']);
  });

  it('площадка: поставленные здания, кроме своего; по умолчанию - самый большой этаж базового', () => {
    const floors = [
      floor({ job_id: 'own', group_key: 'k1', page_index: 1 }),
      floor({ job_id: 'small', group_key: 'base', page_index: 2, outline: [[0, 0], [1000, 0], [1000, 1000], [0, 1000]] }),
      floor({ job_id: 'big', group_key: 'base', page_index: 3, outline: [[0, 0], [50000, 0], [50000, 20000], [0, 20000]] }),
      floor({ job_id: 'huge-other', group_key: 'axes', page_index: 4, outline: [[0, 0], [90000, 0], [90000, 90000], [0, 90000]] }),
      floor({ job_id: 'lost', group_key: 'lost', page_index: 5 }),
    ];
    const groups = [group('k1', 'none'), group('base', 'reference'), group('axes', 'axes'), group('lost', 'none')];
    const result = targetFloorsOf(floors, groups, 'k1');
    expect(result.floors.map((item) => item.job_id).sort()).toEqual(['big', 'huge-other', 'small']);
    expect(result.defaultKey).toBe('big:3:0');
  });

  it('нет поставленных зданий - предлагать нечего', () => {
    expect(targetFloorsOf([floor({})], [group('k1', 'none')], 'k1')).toEqual({ floors: [], defaultKey: null });
  });
});
