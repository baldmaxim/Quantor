import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { WorkspaceModeSwitch } from './WorkspaceModeSwitch';

/** Переключатель режима рабочей области «Листы | CAD». */

describe('WorkspaceModeSwitch', () => {
  it('отмечает текущий режим', () => {
    render(<WorkspaceModeSwitch mode="cad" onChange={vi.fn()} />);
    expect(screen.getByRole('radiogroup', { name: 'Режим рабочей области' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'CAD' })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('radio', { name: 'Листы' })).toHaveAttribute('aria-checked', 'false');
  });

  it('клик по другому режиму сообщает о выборе', async () => {
    const onChange = vi.fn();
    render(<WorkspaceModeSwitch mode="sheets" onChange={onChange} />);
    await userEvent.click(screen.getByRole('radio', { name: 'CAD' }));
    expect(onChange).toHaveBeenCalledWith('cad');
  });

  it('клик по текущему режиму ничего не меняет', async () => {
    const onChange = vi.fn();
    render(<WorkspaceModeSwitch mode="sheets" onChange={onChange} />);
    await userEvent.click(screen.getByRole('radio', { name: 'Листы' }));
    expect(onChange).not.toHaveBeenCalled();
  });
});
