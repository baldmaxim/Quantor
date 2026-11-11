import type { CadConstructionMaterialRead } from '@quantor/api-client';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { construction, constructionsRead } from '@/lib/cad/constructions-fixtures';

import { ConstructionsTotals } from './ConstructionsTotals';

const documentMaterial: CadConstructionMaterialRead = {
  value: 'aerated_concrete',
  source: 'document',
  hint_status: 'matched',
  evidence: [],
};

describe('ConstructionsTotals: ГКЛ и материал из документа', () => {
  it('группа ГКЛ - в м², объём «—»; материал группы помечен «(документ)»', () => {
    const base = construction({ id: 'x' });
    const data = constructionsRead({
      constructions: [
        construction({ id: 'm', material: documentMaterial }),
        construction({
          id: 'p',
          kind: 'frame_partition',
          computed: { ...base.computed, volume_m3: null },
        }),
      ],
      totals: [
        {
          kind: 'masonry',
          thickness_mm: 120,
          material: 'aerated_concrete',
          count: 1,
          length_m: 5,
          wall_area_m2: 13.5,
          volume_m3: 1.62,
        },
        {
          kind: 'frame_partition',
          thickness_mm: 120,
          material: null,
          count: 1,
          length_m: 5,
          wall_area_m2: 13.5,
          volume_m3: null,
        },
      ],
    });
    render(<ConstructionsTotals data={data} activeGroup={null} onSelectGroup={vi.fn()} />);
    expect(screen.getByText('Газобетон (документ)')).toBeInTheDocument();
    const row = screen.getByRole('button', { name: 'Каркасная перегородка ГКЛ' }).closest('tr');
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText('—')).toBeInTheDocument();
    expect(screen.getByText('Итого ГКЛ (по площади)')).toBeInTheDocument();
  });
});

describe('ConstructionsTotals: плита перекрытия', () => {
  const base = construction({ id: 'x' });
  const slab = construction({
    id: 'slab',
    kind: 'floor_slab',
    thickness_nominal_mm: 200,
    computed: {
      ...base.computed,
      thickness_mm: 200,
      height_mm: null,
      length_m: null,
      wall_area_m2: null,
      area_m2: 52.5,
      volume_m3: 10.5,
    },
  });
  const data = constructionsRead({
    constructions: [construction({ id: 'm' }), slab],
    totals: [
      {
        kind: 'masonry',
        thickness_mm: 120,
        material: null,
        count: 1,
        length_m: 5,
        wall_area_m2: 13.5,
        volume_m3: 1.62,
      },
      {
        kind: 'floor_slab',
        thickness_mm: 200,
        material: null,
        count: 1,
        length_m: 0,
        wall_area_m2: 0,
        volume_m3: 10.5,
        area_m2: 52.5,
      },
    ],
  });

  it('отдельный блок после стен: толщина, площадь и объём; в итог кладки не входит', () => {
    render(<ConstructionsTotals data={data} activeGroup={null} onSelectGroup={vi.fn()} />);
    const block = screen.getByRole('group', { name: 'Плита перекрытия' });
    expect(within(block).getByText('200')).toBeInTheDocument();
    expect(within(block).getByText('52,5')).toBeInTheDocument();
    expect(within(block).getByText('10,5')).toBeInTheDocument();
    // В таблице стен плиты нет; итог кладки - только кладка.
    expect(screen.queryAllByRole('button', { name: 'Плита перекрытия' })).toHaveLength(0);
    const masonryTotal = screen.getByText('Итого кладка').closest('tr') as HTMLElement;
    expect(within(masonryTotal).getByText('1,62')).toBeInTheDocument();
    expect(within(masonryTotal).queryByText('10,5')).toBeNull();
    expect(screen.queryByText('Итого монолит')).toBeNull();
  });

  it('клик по строке плиты выбирает её конструкцию', () => {
    const onSelectGroup = vi.fn();
    render(<ConstructionsTotals data={data} activeGroup={null} onSelectGroup={onSelectGroup} />);
    const block = screen.getByRole('group', { name: 'Плита перекрытия' });
    fireEvent.click(within(block).getByText('200'));
    expect(onSelectGroup).toHaveBeenCalledWith('floor_slab|200|', ['slab']);
  });

  it('только плита без стен: таблицы стен нет, блок плиты есть', () => {
    const only = constructionsRead({
      constructions: [slab],
      totals: [data.totals[1] as (typeof data.totals)[number]],
    });
    render(<ConstructionsTotals data={only} activeGroup={null} onSelectGroup={vi.fn()} />);
    expect(screen.getByRole('group', { name: 'Плита перекрытия' })).toBeInTheDocument();
    expect(screen.queryByText('Итого кладка')).toBeNull();
    expect(screen.queryByText(/Посчитанных конструкций нет/)).toBeNull();
  });
});

describe('ConstructionsTotals: монолитные перемычки', () => {
  const data = constructionsRead({
    constructions: [construction({ id: 'm' })],
    totals: [
      {
        kind: 'masonry',
        thickness_mm: 200,
        material: null,
        count: 1,
        length_m: 5,
        wall_area_m2: 14,
        volume_m3: 2.8,
      },
      {
        kind: 'monolith_wall',
        element: 'lintel',
        thickness_mm: 200,
        material: 'monolith_concrete',
        count: 2,
        length_m: 1.9,
        wall_area_m2: 0,
        volume_m3: 0.28,
      },
    ],
    summary: {
      total_count: 1,
      thickness_check_count: 0,
      height_missing_count: 0,
      unaccounted_gap_openings: 0,
      door_openings_without_host: 0,
      lintels_without_volume: 3,
    },
  });

  it('строка «Монолит — перемычки»: шт., длина, объём; площадь стены - прочерк; входит в итог монолита', () => {
    const onSelectGroup = vi.fn();
    render(<ConstructionsTotals data={data} activeGroup={null} onSelectGroup={onSelectGroup} />);
    const row = screen.getByText('Монолит — перемычки').closest('tr') as HTMLElement;
    expect(within(row).getByText('2')).toBeInTheDocument();
    expect(within(row).getByText('1,9')).toBeInTheDocument();
    expect(within(row).getByText('0,28')).toBeInTheDocument();
    expect(within(row).getByText('—')).toBeInTheDocument();
    const total = screen.getByText('Итого монолит').closest('tr') as HTMLElement;
    expect(within(total).getByText('0,28')).toBeInTheDocument();
    const masonryTotal = screen.getByText('Итого кладка').closest('tr') as HTMLElement;
    expect(within(masonryTotal).queryByText('0,28')).toBeNull();
    fireEvent.click(row);
    expect(onSelectGroup).not.toHaveBeenCalled();
  });

  it('счётчик перемычек без объёма - в блоке «не вошло»', () => {
    render(<ConstructionsTotals data={data} activeGroup={null} onSelectGroup={vi.fn()} />);
    expect(screen.getByText('Перемычки без объёма — 3')).toBeInTheDocument();
  });
});
