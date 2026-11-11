import type { CadConstructionMaterialRead } from '@quantor/api-client';
import { render, screen, within } from '@testing-library/react';
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
