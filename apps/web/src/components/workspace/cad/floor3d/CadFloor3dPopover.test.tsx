import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { floor3dFixture } from '@/lib/cad/floor3d-fixtures';

import { CadFloor3dPopover } from './CadFloor3dPopover';

const mount = (key: string) => {
  const onDecide = vi.fn();
  render(
    <CadFloor3dPopover
      pick={{ kind: 'hole', category: 'hole', id: key }}
      model={floor3dFixture()}
      anchor={{ x: 10, y: 10 }}
      bounds={{ width: 600, height: 400 }}
      saving={false}
      error={null}
      onDecide={onDecide}
      onClose={vi.fn()}
    />,
  );
  return onDecide;
};

describe('плашка отверстия: кнопки по состоянию', () => {
  it('кандидат - обе кнопки', () => {
    const onDecide = mount('h1');
    fireEvent.click(screen.getByRole('button', { name: 'Отверстие' }));
    fireEvent.click(screen.getByRole('button', { name: 'Не отверстие' }));
    expect(onDecide.mock.calls).toEqual([
      ['h1', true],
      ['h1', false],
    ]);
  });

  it('включено - только «Не отверстие»', () => {
    mount('h2');
    expect(screen.queryByRole('button', { name: 'Отверстие' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Не отверстие' })).toBeInTheDocument();
  });

  it('не отверстие - состояние и только «Отверстие»', () => {
    const onDecide = mount('h3');
    expect(screen.getByRole('dialog', { name: 'Отверстие плиты' })).toHaveTextContent('не отверстие');
    expect(screen.queryByRole('button', { name: 'Не отверстие' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Отверстие' }));
    expect(onDecide).toHaveBeenCalledWith('h3', true);
  });
});
