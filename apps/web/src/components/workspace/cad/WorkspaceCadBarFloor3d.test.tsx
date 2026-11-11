import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { diagnostics } from '@/components/cad/viewer/fixtures';

import type { IWorkspaceCadBarProps } from './types';
import { WorkspaceCadBar } from './WorkspaceCadBar';

const mount = (mode: 'plan' | '3d', onModeChange = vi.fn()) => {
  const props: IWorkspaceCadBarProps = {
    diagnostics: diagnostics(),
    views: [1],
    view: 1,
    onViewChange: vi.fn(),
    onFit: vi.fn(),
    notices: [],
    loading: false,
    floor3d: { mode, onModeChange },
  };
  render(<WorkspaceCadBar {...props} />);
  return { props, onModeChange };
};

describe('переключатель «План | 3D»', () => {
  it('показывает оба режима; режим «План» выбран, «Вписать» плана на месте', () => {
    mount('plan');
    const group = screen.getByRole('group', { name: 'Режим холста' });
    expect(group).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'План' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: '3D' })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('button', { name: 'Вписать' })).toBeInTheDocument();
  });

  it('«3D» сообщает о выборе режима', () => {
    const { onModeChange } = mount('plan');
    fireEvent.click(screen.getByRole('button', { name: '3D' }));
    expect(onModeChange).toHaveBeenCalledWith('3d');
  });

  it('в режиме «3D» «Вписать» плана скрыта: у вида свои кнопки', () => {
    mount('3d');
    expect(screen.getByRole('button', { name: '3D' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.queryByRole('button', { name: 'Вписать' })).toBeNull();
  });

  it('без floor3d переключателя нет', () => {
    render(
      <WorkspaceCadBar
        diagnostics={diagnostics()}
        views={[1]}
        view={1}
        onViewChange={vi.fn()}
        onFit={vi.fn()}
        notices={[]}
        loading={false}
      />,
    );
    expect(screen.queryByRole('group', { name: 'Режим холста' })).toBeNull();
  });
});
