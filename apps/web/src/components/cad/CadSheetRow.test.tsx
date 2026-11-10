import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { ISheetResult } from '@/lib/cad/sheet-results';

import { CadSheetRow } from './CadSheetRow';

const HREF = '/projects/p/workspace?revision=r&page=3';

const mount = (result: ISheetResult | null) =>
  render(
    <ul>
      <CadSheetRow
        sheet={{ id: 's', page_index: 2, page_label: '3' } as never}
        href={HREF}
        state="unknown"
        manualEnabled={false}
        checked={false}
        limitReached={false}
        result={result}
        open={false}
        onToggle={vi.fn()}
        onOpenResult={vi.fn()}
      />
    </ul>,
  );

describe('CadSheetRow: переход в рабочую область', () => {
  it('у распознанного листа есть ссылка на вкладку CAD рабочей области', () => {
    mount({ jobId: 'j', kind: 'recognized', view: null, dxf: true });
    expect(screen.getByRole('link', { name: 'В рабочей области' })).toHaveAttribute(
      'href',
      `${HREF}&tab=cad`,
    );
  });

  it.each(['running', 'failed'] as const)('у листа в состоянии %s ссылки нет', (kind) => {
    mount({ jobId: 'j', kind, view: null, dxf: false });
    expect(screen.queryByRole('link', { name: 'В рабочей области' })).toBeNull();
  });

  it('у листа без заданий ссылки нет', () => {
    mount(null);
    expect(screen.queryByRole('link', { name: 'В рабочей области' })).toBeNull();
  });
});
