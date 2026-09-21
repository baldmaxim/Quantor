import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { Button, Dialog, DialogActions } from './index';

/**
 * Модальное окно.
 *
 * Проверяется то, чего не было ни в одной из трёх прежних копий разметки: фон
 * недоступен, фокус не убегает наружу и возвращается назад, а занятое работой
 * окно не закрывается случайным нажатием.
 */

const Harness = ({ busy = false, onExited }: { busy?: boolean; onExited?: () => void }) => {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Открыть
      </button>
      <p>Текст страницы</p>
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        busy={busy}
        title="Новый проект"
        description="Название и файлы"
        onExited={onExited}
        footer={
          <DialogActions>
            <Button onClick={() => setOpen(false)}>Отмена</Button>
            <Button variant="primary">Создать</Button>
          </DialogActions>
        }
      >
        <input aria-label="Название" />
      </Dialog>
    </>
  );
};

const open = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.click(screen.getByRole('button', { name: 'Открыть' }));
  return screen.getByRole('dialog');
};

describe('модальное окно', () => {
  it('связывает заголовок и пояснение с окном', async () => {
    const user = userEvent.setup();
    render(<Harness />);

    const dialog = await open(user);

    expect(dialog).toHaveAccessibleName('Новый проект');
    expect(dialog).toHaveAccessibleDescription('Название и файлы');
  });

  it('закрывается по Escape', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await open(user);

    await user.keyboard('{Escape}');

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('занятое работой окно Escape не закрывает', async () => {
    const user = userEvent.setup();
    render(<Harness busy />);
    await open(user);

    await user.keyboard('{Escape}');

    // Загрузка идёт: закрыть окно значило бы оборвать её молча.
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('прячет страницу под окном от программ чтения', async () => {
    const user = userEvent.setup();
    // container — это узел страницы в body; окно портал кладёт в body рядом с ним.
    const { container } = render(<Harness />);

    await open(user);

    // Всё в body, кроме окна, помечается inert: иначе диктор продолжает читать
    // фон, а Tab уходит на страницу под подложкой.
    expect(container).toHaveAttribute('inert');

    await user.keyboard('{Escape}');
    await waitFor(() => expect(container).not.toHaveAttribute('inert'));
  });

  it('возвращает фокус на кнопку, которой его открыли', async () => {
    const user = userEvent.setup();
    render(<Harness />);

    const trigger = screen.getByRole('button', { name: 'Открыть' });
    await user.click(trigger);
    await user.keyboard('{Escape}');

    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it('сообщает о закрытии, чтобы можно было обнулить состояние', async () => {
    const user = userEvent.setup();
    const onExited = vi.fn();
    render(<Harness onExited={onExited} />);
    await open(user);

    await user.keyboard('{Escape}');

    await waitFor(() => expect(onExited).toHaveBeenCalledTimes(1));
  });

  it('держит футер отдельно от прокручиваемого тела', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const dialog = await open(user);

    // Кнопки закреплены внизу карточки: уезжая вместе с длинным списком файлов,
    // они переставали быть видны как раз тогда, когда нужны.
    const footer = dialog.querySelector('footer');
    expect(footer).not.toBeNull();
    expect(footer?.querySelector('button')).toBeTruthy();
    expect(dialog.querySelector('.scroll-area')?.contains(footer ?? null)).toBe(false);
  });
});
