import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mutations = vi.hoisted(() => ({
  retry: vi.fn(),
  create: vi.fn(),
}));

vi.mock('@/lib/cad/queries', () => ({
  // isPending намеренно всегда false: проверяется защита до обновления состояния.
  useRetryCadJob: () => ({
    mutate: mutations.retry,
    isPending: false,
    isError: false,
    error: null,
  }),
  useCreateCadJob: () => ({
    mutate: mutations.create,
    isPending: false,
    isError: false,
    error: null,
  }),
}));

import type { CadAttemptRead, CadJobRead } from '@quantor/api-client';

import { CadJobActions } from './CadJobActions';

const job = {
  job_id: 'j1',
  status: 'failed',
  retryable: true,
  review_required: false,
} as unknown as CadJobRead;
const attempt = {
  attempt: 1,
  pages: { planned: [0, 2], requested: [], total: 3 },
} as unknown as CadAttemptRead;

const mount = () =>
  render(
    <CadJobActions
      projectId="p"
      revisionId="r"
      job={job}
      attempt={attempt}
      onJobCreated={vi.fn()}
      onRetried={vi.fn()}
    />,
  );

beforeEach(() => {
  mutations.retry.mockReset();
  mutations.create.mockReset();
});

describe('CadJobActions: двойное нажатие', () => {
  it('«Повторить» отправляет один запрос, пока первый не завершён', () => {
    mount();
    const button = screen.getByRole('button', { name: /Повторить/ });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(mutations.retry).toHaveBeenCalledTimes(1);

    // Запрос завершён (успехом или отказом) - кнопка снова рабочая.
    const options = mutations.retry.mock.calls[0]?.[1] as { onSettled: () => void };
    options.onSettled();
    fireEvent.click(button);
    expect(mutations.retry).toHaveBeenCalledTimes(2);
  });

  it('«Запустить по выбранным страницам» отправляет один запрос', () => {
    mount();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Стр. 1' }));
    const button = screen.getByRole('button', { name: /Запустить по выбранным страницам/ });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(mutations.create).toHaveBeenCalledTimes(1);
    expect(mutations.create.mock.calls[0]?.[0]).toEqual({ pages: [0] });
  });
});
