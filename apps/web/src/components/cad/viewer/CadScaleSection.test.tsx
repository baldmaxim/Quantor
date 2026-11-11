import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { CadScaleSection } from './CadScaleSection';
import { scale } from './fixtures';

const text = () => screen.getByTestId('cad-scale-summary');

describe('CadScaleSection', () => {
  it('подтверждён: «Масштаб 1:N», статус словами, без технических строк', () => {
    render(<CadScaleSection scale={scale()} />);
    expect(text()).toHaveTextContent('Масштаб 1:100');
    expect(screen.getByText('подтверждён')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
    // Отклонения у масштаба нет - строки нет.
    expect(screen.queryByText(/Отклонение/)).toBeNull();
    [
      /мм на точку/i,
      /мм\/pt/i,
      /Метод/,
      /Контролей/,
      /Цепочек:/,
      /Независимые оси/,
      /Конфликтов привязки/,
      /Выпуск разрешён/,
      /HOLD/,
    ].forEach((pattern) => expect(screen.queryByText(pattern)).toBeNull());
  });

  it('таблица контролей по размерным цепочкам после строки масштаба', () => {
    render(<CadScaleSection scale={scale()} />);
    const table = screen.getByRole('table');
    ['Цепочка', 'Роль', 'Подпись, мм', 'По масштабу, мм', 'Невязка, мм', 'Допуск, мм'].forEach(
      (name) => expect(within(table).getByText(name)).toBeInTheDocument(),
    );
    expect(within(table).getByText(/^3\s000/)).toBeInTheDocument();
    expect(within(table).getAllByRole('row')).toHaveLength(3);
  });

  it('без контролей таблицы нет', () => {
    render(<CadScaleSection scale={scale({ controls: [] })} />);
    expect(screen.queryByRole('table')).toBeNull();
    expect(screen.getByText(/Размерных цепочек для контроля не найдено/)).toBeInTheDocument();
  });

  it('масштаб калибровки человека: 1:N из мм/pt и отклонение от цепочек в процентах', () => {
    render(
      <CadScaleSection
        scale={scale({
          source: 'operator_calibration',
          operator_mm_per_pt: 70.5556,
          mm_per_pdf_point: 70.5556,
          deviation: 0.023,
        })}
      />,
    );
    expect(text()).toHaveTextContent('Масштаб 1:200');
    expect(text()).toHaveTextContent(/Отклонение от размерных цепочек: 2,3\s*%/);
    expect(screen.queryByText('70,5556')).toBeNull();
  });

  it('не подтверждён: статус и причина отказа текстом', () => {
    render(
      <CadScaleSection
        scale={scale({
          passed: false,
          hold_reasons: ['Проверьте калибровку'],
          reason: 'Проверьте калибровку',
        })}
      />,
    );
    expect(screen.getByText('не подтверждён')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Масштаб не подтверждён');
    expect(screen.getByRole('alert')).toHaveTextContent('Проверьте калибровку');
  });

  it('не подтверждён без списка причин: показана общая причина', () => {
    render(
      <CadScaleSection
        scale={scale({ passed: false, hold_reasons: [], reason: 'Отклонение выше допуска' })}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Отклонение выше допуска');
  });

  it('движок не записал проверку масштаба', () => {
    render(<CadScaleSection scale={null} />);
    expect(screen.getByText(/не записал проверку масштаба/)).toBeInTheDocument();
  });
});
