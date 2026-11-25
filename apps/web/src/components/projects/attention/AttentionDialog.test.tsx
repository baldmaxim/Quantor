import * as client from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AttentionDialog } from './AttentionDialog';
import { docItems, scaleItem, type AttentionItem } from './attentionQueue';
import { candidate, question, questionsOut, scaleFailedSheet } from './fixtures';

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof client>()),
  putDocAnswer: vi.fn(),
  rejectDocCandidate: vi.fn(),
}));

const ok = (data: unknown) => Promise.resolve({ data }) as never;

const mount = (items: readonly AttentionItem[], onSnooze = vi.fn(), onClose = vi.fn()) => {
  vi.mocked(client.putDocAnswer)
    .mockReset()
    .mockImplementation(() => ok({}));
  vi.mocked(client.rejectDocCandidate)
    .mockReset()
    .mockImplementation(() => ok(candidate()));
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <AttentionDialog projectId="p-1" open items={items} onClose={onClose} onSnooze={onSnooze} />
    </QueryClientProvider>,
  );
  return { onSnooze, onClose };
};

const withCandidate = () =>
  docItems(questionsOut([question({ candidates: [candidate({ id: 'c-7' })] })]));

describe('окно прямых вопросов', () => {
  beforeEach(() => vi.clearAllMocks());

  it('показывает лучшего кандидата с источником и счётчик «ещё N»', () => {
    const items = docItems(
      questionsOut([
        question({ candidates: [candidate()] }),
        question({ code: 'slab_thickness', title: 'Толщина плиты' }),
      ]),
    );
    mount(items);

    expect(screen.getByText('Подтвердить?')).toBeInTheDocument();
    expect(screen.getByText('2700')).toBeInTheDocument();
    expect(screen.getByText(/АР_ПЗ\.pdf, стр\. 5/)).toBeInTheDocument();
    expect(screen.getByText('Ещё 1')).toBeInTheDocument();
  });

  it('«Подтвердить» сохраняет ответ по кандидату тем же PUT', async () => {
    const user = userEvent.setup();
    mount(withCandidate());

    await user.click(screen.getByRole('button', { name: 'Подтвердить' }));

    await waitFor(() => expect(client.putDocAnswer).toHaveBeenCalledTimes(1));
    expect(client.putDocAnswer).toHaveBeenCalledWith({
      throwOnError: true,
      path: { project_id: 'p-1', code: 'clear_height' },
      body: { source: 'document', candidate_id: 'c-7' },
    });
  });

  it('«Другое значение» сохраняет введённое значение с пояснением', async () => {
    const user = userEvent.setup();
    mount(withCandidate());

    await user.click(screen.getByRole('button', { name: 'Другое значение' }));
    await user.type(screen.getByLabelText('Значение, мм'), '2750');
    await user.type(screen.getByLabelText('Откуда значение'), 'разрез 1-1');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));

    await waitFor(() => expect(client.putDocAnswer).toHaveBeenCalledTimes(1));
    const call = vi.mocked(client.putDocAnswer).mock.calls[0]?.[0];
    expect(call?.path).toEqual({ project_id: 'p-1', code: 'clear_height' });
    expect(call?.body).toMatchObject({ source: 'manual', note: 'разрез 1-1' });
    expect(JSON.stringify(call?.body)).toContain('2750');
  });

  it('без кандидата просит ввести значение сразу', () => {
    mount(docItems(questionsOut([question()])));

    expect(screen.getByText('Введите значение')).toBeInTheDocument();
    expect(screen.getByLabelText('Значение, мм')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Подтвердить' })).not.toBeInTheDocument();
  });

  it('«Отклонить кандидата» вызывает отклонение', async () => {
    const user = userEvent.setup();
    mount(withCandidate());

    await user.click(screen.getByRole('button', { name: 'Отклонить кандидата' }));

    await waitFor(() => expect(client.rejectDocCandidate).toHaveBeenCalledTimes(1));
    expect(client.rejectDocCandidate).toHaveBeenCalledWith({
      throwOnError: true,
      path: { project_id: 'p-1', candidate_id: 'c-7' },
    });
  });

  it('«Позже» откладывает текущий вопрос', async () => {
    const user = userEvent.setup();
    const { onSnooze } = mount(withCandidate());

    await user.click(screen.getByRole('button', { name: 'Позже' }));

    expect(onSnooze).toHaveBeenCalledWith('doc:clear_height');
  });

  it('вопрос о масштабе ведёт к калибровке и ничего не сохраняет', () => {
    const item = scaleItem('p-1', 'r-1', 'АР.pdf', scaleFailedSheet(0));
    mount(item ? [item] : []);

    const link = screen.getByRole('link', { name: 'Откалибровать' });
    expect(link).toHaveAttribute('href', expect.stringContaining('/projects/p-1/workspace'));
    expect(client.putDocAnswer).not.toHaveBeenCalled();
  });
});
