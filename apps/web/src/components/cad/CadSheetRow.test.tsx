import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { ISheetResult } from '@/lib/cad/sheet-results';
import type { SheetCalibrationState } from '@/lib/cad/sheets';

import { CadSheetRow } from './CadSheetRow';


const mount = (
  result: ISheetResult | null,
  open = false,
  state: SheetCalibrationState = 'unknown',
) => {
  const onOpen = vi.fn();
  render(
    <ul>
      <CadSheetRow
        sheet={{ id: 's', page_index: 2, page_label: '3' } as never}
        state={state}
        result={result}
        open={open}
        onOpen={onOpen}
      />
    </ul>,
  );
  return { onOpen };
};

describe('CadSheetRow', () => {
  it.each([
    ['распознанный', { jobId: 'j', kind: 'recognized', view: null, dxf: true } as const],
    ['идущий', { jobId: 'j', kind: 'running', view: null, dxf: false } as const],
    ['упавший', { jobId: 'j', kind: 'failed', view: null, dxf: false } as const],
    ['без заданий', null],
  ])('лист %s: вся строка - одна кнопка открытия, чекбокса нет', (_, result) => {
    const { onOpen } = mount(result);
    expect(screen.queryByRole('checkbox')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /Стр. 3/ }));
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it('кнопка строки не уже 44 px по высоте и занимает всю ширину', () => {
    mount(null);
    const button = screen.getByRole('button', { name: /Стр. 3/ });
    expect(button.className).toContain('min-h-[44px]');
    expect(button.className).toContain('w-full');
  });

  it('бейдж результата внутри кнопки строки', () => {
    mount({ jobId: 'j', kind: 'recognized', view: null, dxf: true });
    expect(screen.getByRole('button', { name: /DXF есть/ })).toBeInTheDocument();
  });

  it('открытый лист подсвечен и помечен aria-current', () => {
    mount(null, true);
    expect(screen.getByRole('button', { name: /Стр. 3/ })).toHaveAttribute('aria-current', 'true');
  });

  it('нет калибровки: бейдж без ссылки «Откалибровать»', () => {
    mount(null, true, 'missing');
    expect(screen.getByText('Нет калибровки')).toBeInTheDocument();
    expect(screen.queryByText('Откалибровать')).toBeNull();
  });

  it('калибровка есть: бейдж без ссылки; неизвестная - без бейджа', () => {
    const { onOpen } = mount(null, true, 'calibrated');
    expect(screen.getByText('Калибровка есть')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Откалибровать' })).toBeNull();
    expect(onOpen).not.toHaveBeenCalled();
  });

  it('состояние калибровки неизвестно: бейджей калибровки нет', () => {
    mount(null);
    expect(screen.queryByText('Калибровка есть')).toBeNull();
    expect(screen.queryByText('Нет калибровки')).toBeNull();
  });
});
