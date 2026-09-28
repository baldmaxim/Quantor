import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { factType, readinessRow } from './__fixtures__/calc';

import { ReadinessTable } from './ReadinessTable';

/**
 * Требования системы. Главное — честность статуса: найденное показывает значение и источник,
 * ненайденное — прочерк и причину, но никогда не ноль.
 */

const TYPES = new Map([['floor.apartments_count', factType()]]);

describe('матрица требований системы', () => {
  it('найденное показывает место, значение, единицу и источник', () => {
    render(<ReadinessTable rows={[readinessRow()]} factTypes={TYPES} />);
    const row = screen.getByText('Квартиры на этажах').closest('li');
    expect(row).not.toBeNull();
    const cells = within(row as HTMLElement);
    expect(cells.getByText('найдено')).toBeInTheDocument();
    expect(cells.getByText('корп. 1 · эт. 2–24: 9 кв.')).toBeInTheDocument();
    expect(cells.getByText('Квартирография · АР.pdf')).toBeInTheDocument();
  });

  it('проверено и не найдено — прочерк и причина, а не ноль', () => {
    const missing = readinessRow({
      status: 'MISSING',
      values: [],
      reason: 'Проверено документов: 2 — не найдено',
    });
    render(<ReadinessTable rows={[missing]} factTypes={TYPES} />);
    expect(screen.getByText('не найдено')).toBeInTheDocument();
    expect(screen.getByText('—')).toBeInTheDocument();
    expect(screen.getByText('Проверено документов: 2 — не найдено')).toBeInTheDocument();
    expect(screen.queryByText(/: 0/)).toBeNull();
  });

  it('непроверенный документ не выдаёт себя за «не найдено»', () => {
    const pending = readinessRow({
      status: 'NOT_INSPECTED',
      values: [],
      reason: 'Не проверено документов: 1 из 2',
    });
    render(<ReadinessTable rows={[pending]} factTypes={TYPES} />);
    expect(screen.getByText('не проверено')).toBeInTheDocument();
    expect(screen.queryByText('не найдено')).toBeNull();
  });

  it('ВОР Заказчика показан отдельно и только для сверки', () => {
    const vor = readinessRow({ status: 'MISSING', values: [], excluded_count: 1 });
    render(<ReadinessTable rows={[vor]} factTypes={TYPES} />);
    expect(screen.getByText('В ВОР Заказчика: 1 — только сверка')).toBeInTheDocument();
  });
});
