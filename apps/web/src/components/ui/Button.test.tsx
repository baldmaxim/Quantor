import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { Button, ButtonLink, buttonClassName } from './index';

/**
 * Кнопка.
 *
 * Проверяется то, ради чего появились состояние работы и общий набор классов:
 * занятая кнопка не принимает второе нажатие, подпись при этом меняется, а
 * ширина остаётся прежней — иначе соседняя «Отмена» прыгает под курсором.
 */

describe('кнопка', () => {
  it('во время работы называется подписью работы и занята', () => {
    render(
      <Button variant="primary" loading loadingLabel="Создаём…">
        Создать проект
      </Button>,
    );

    const button = screen.getByRole('button', { name: 'Создаём…' });
    expect(button).toHaveAttribute('aria-busy', 'true');
    expect(button).toBeDisabled();
  });

  it('не отправляет запрос повторно, пока идёт первый', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(
      <Button loading loadingLabel="Создаём…" onClick={onClick}>
        Создать проект
      </Button>,
    );

    await user.click(screen.getByRole('button', { name: 'Создаём…' }));

    expect(onClick).not.toHaveBeenCalled();
  });

  it('держит ширину обеих подписей, чтобы кнопка не прыгала', () => {
    render(
      <Button loading={false} loadingLabel="Создаём…">
        Создать проект
      </Button>,
    );

    const button = screen.getByRole('button');
    // Обе подписи в разметке, но доступное имя одно: мерки скрыты от диктора.
    expect(button.textContent).toContain('Создаём…');
    expect(button).toHaveAccessibleName('Создать проект');
  });

  it('обычная кнопка остаётся без лишней разметки', () => {
    render(<Button>Отмена</Button>);

    const button = screen.getByRole('button', { name: 'Отмена' });
    expect(button).not.toHaveAttribute('aria-busy');
    expect(button).toBeEnabled();
  });

  it('ссылка-кнопка остаётся ссылкой и получает тот же вид', () => {
    render(
      <ButtonLink href="/projects" variant="primary">
        К списку проектов
      </ButtonLink>,
    );

    const link = screen.getByRole('link', { name: 'К списку проектов' });
    expect(link).toHaveAttribute('href', '/projects');
    // Метка ctl нужна правилу тап-целей: <a> под селектор button не попадает.
    expect(link.className).toContain('ctl');
    expect(link.className).toBe(buttonClassName({ variant: 'primary' }));
  });
});
