import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

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

  it('ручной ввод предлагается там, где значения нет, а не поверх найденного', async () => {
    const onEnter = vi.fn();
    const missing = readinessRow({ requirement_id: 'r-2', status: 'MISSING', values: [] });
    render(<ReadinessTable rows={[readinessRow(), missing]} factTypes={TYPES} onEnter={onEnter} />);
    const [button] = screen.getAllByRole('button', { name: 'Ввести значение' });
    expect(screen.getAllByRole('button', { name: 'Ввести значение' })).toHaveLength(1);
    await userEvent.click(button as HTMLElement);
    expect(onEnter).toHaveBeenCalledWith(missing);
  });

  it('без права ввода кнопки нет', () => {
    render(
      <ReadinessTable rows={[readinessRow({ status: 'MISSING', values: [] })]} factTypes={TYPES} />,
    );
    expect(screen.queryByRole('button', { name: 'Ввести значение' })).toBeNull();
  });

  it('расхождение открывает варианты по идентификатору конфликта', async () => {
    const onResolve = vi.fn();
    const [value] = readinessRow().values;
    const conflicted = readinessRow({
      status: 'CONFLICTED',
      values: [
        {
          ...(value as NonNullable<typeof value>),
          state: 'UNRESOLVED',
          value: null,
          conflict_id: 'c-1',
        },
      ],
    });
    render(<ReadinessTable rows={[conflicted]} factTypes={TYPES} onResolve={onResolve} />);
    expect(screen.queryByRole('button', { name: 'Ввести значение' })).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'Варианты' }));
    expect(onResolve).toHaveBeenCalledWith('c-1');
  });
});
