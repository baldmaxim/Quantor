import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';

import { ClearableInput } from './ClearableInput';

/**
 * Поле с крестиком: видимость, очистка и фокус после неё.
 */

const Controlled = ({
  initial,
  ...rest
}: {
  initial: string;
  disabled?: boolean;
  readOnly?: boolean;
}) => {
  const [value, setValue] = useState(initial);
  return (
    <ClearableInput
      label="Подпись"
      value={value}
      onChange={(event) => setValue(event.target.value)}
      onClear={() => setValue('')}
      {...rest}
    />
  );
};

describe('поле с крестиком', () => {
  it('у пустого поля крестика нет', () => {
    render(<Controlled initial="" />);

    expect(screen.queryByRole('button', { name: 'Очистить: Подпись' })).toBeNull();
  });

  it('у заблокированного и только читаемого поля крестика нет', () => {
    const { rerender } = render(<Controlled initial="АР" disabled />);
    expect(screen.queryByRole('button')).toBeNull();

    rerender(<Controlled initial="АР" readOnly />);
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('стирает написанное, возвращает фокус в поле и не отправляет форму', async () => {
    const user = userEvent.setup();
    let submitted = false;
    render(
      <form onSubmit={() => (submitted = true)}>
        <Controlled initial="Первая" />
      </form>,
    );

    await user.click(screen.getByRole('button', { name: 'Очистить: Подпись' }));

    const field = screen.getByRole('textbox', { name: 'Подпись' });
    expect(field).toHaveValue('');
    expect(field).toHaveFocus();
    expect(submitted).toBe(false);
    expect(screen.queryByRole('button', { name: 'Очистить: Подпись' })).toBeNull();
  });
});
