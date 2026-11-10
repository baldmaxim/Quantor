import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { ISheetResult } from '@/lib/cad/sheet-results';

import { CadSheetRow } from './CadSheetRow';

const HREF = '/projects/p/workspace?revision=r&page=3';

const mount = (result: ISheetResult | null, open = false) => {
  const onOpen = vi.fn();
  const onToggle = vi.fn();
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
        open={open}
        onToggle={onToggle}
        onOpen={onOpen}
      />
    </ul>,
  );
  return { onOpen, onToggle };
};

describe('CadSheetRow', () => {
  it.each([
    ['распознанный', { jobId: 'j', kind: 'recognized', view: null, dxf: true } as const],
    ['идущий', { jobId: 'j', kind: 'running', view: null, dxf: false } as const],
    ['упавший', { jobId: 'j', kind: 'failed', view: null, dxf: false } as const],
    ['без заданий', null],
  ])('лист %s: строка открывает лист, чекбокс - отдельная цель', (_, result) => {
    const { onOpen, onToggle } = mount(result);
    fireEvent.click(screen.getByRole('button', { name: /Стр. 3/ }));
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onToggle).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Стр. 3' }));
    expect(onToggle).toHaveBeenCalledTimes(1);
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it('ссылки «В рабочей области» нет: строка и есть рабочая область', () => {
    mount({ jobId: 'j', kind: 'recognized', view: null, dxf: true });
    expect(screen.queryByRole('link', { name: 'В рабочей области' })).toBeNull();
  });

  it('открытый лист подсвечен и помечен aria-current', () => {
    mount(null, true);
    expect(screen.getByRole('button', { name: /Стр. 3/ })).toHaveAttribute('aria-current', 'true');
  });
});
