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

describe('переключатель «План ⇄ 3D»', () => {
  it('один переключатель; режим «План» — выключен, «Вписать» плана на месте', () => {
    mount('plan');
    expect(screen.getByRole('switch', { name: 'Режим холста: 3D' })).toHaveAttribute('aria-checked', 'false');
    expect(screen.getByRole('button', { name: 'Вписать' })).toBeInTheDocument();
  });

  it('клик на плане включает 3D', () => {
    const { onModeChange } = mount('plan');
    fireEvent.click(screen.getByRole('switch', { name: 'Режим холста: 3D' }));
    expect(onModeChange).toHaveBeenCalledWith('3d');
  });

  it('клик в 3D возвращает на план; «Вписать» плана скрыта', () => {
    const { onModeChange } = mount('3d');
    const toggle = screen.getByRole('switch', { name: 'Режим холста: 3D' });
    expect(toggle).toHaveAttribute('aria-checked', 'true');
    expect(screen.queryByRole('button', { name: 'Вписать' })).toBeNull();
    fireEvent.click(toggle);
    expect(onModeChange).toHaveBeenCalledWith('plan');
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
    expect(screen.queryByRole('switch')).toBeNull();
  });
});
