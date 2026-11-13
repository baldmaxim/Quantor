import * as client from '@quantor/api-client';
import type {
  DocAnswerOut,
  DocCandidateOut,
  DocQuestionOut,
  DocQuestionsOut,
} from '@quantor/api-client';
import * as queries from '@/lib/queries';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { DocQuestionsScreen } from './DocQuestionsScreen';

vi.mock('@/lib/queries', async (importOriginal) => ({
  ...(await importOriginal<typeof queries>()),
  useMeta: vi.fn(),
  useFeatures: vi.fn(),
  useProject: vi.fn(),
}));

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof client>()),
  getDocQuestions: vi.fn(),
  putDocAnswer: vi.fn(),
  rejectDocCandidate: vi.fn(),
  removeDocAnswer: vi.fn(),
  startDocQuestionsSearch: vi.fn(),
}));

const ok = (data: unknown) => Promise.resolve({ data }) as never;

const candidate = (patch: Partial<DocCandidateOut> = {}): DocCandidateOut => ({
  id: 'c-1',
  question_code: 'clear_height',
  value: { kind: 'length_mm', display: '2700', numbers: [2700], qualifier: null, code: null },
  value_text: '2700 мм',
  quote: 'Высота помещений в свету 2700 мм',
  revision_id: 'r-1',
  page_index: 4,
  page_label: null,
  file_name: 'АР_ПЗ.pdf',
  building: '9',
  section: '3',
  level: null,
  score: 40,
  occurrences: 2,
  status: 'candidate',
  versions: {},
  created_at: '2026-11-12T10:00:00Z',
  ...patch,
});

const answer = (patch: Partial<DocAnswerOut> = {}): DocAnswerOut => ({
  id: 'a-1',
  question_code: 'clear_height',
  source: 'document',
  scope_building: '9',
  scope_section: null,
  value: { kind: 'length_mm', display: '2700', numbers: [2700], qualifier: null, code: null },
  value_text: '2700 мм',
  candidate_id: 'c-1',
  file_name: 'АР_ПЗ.pdf',
  revision_id: 'r-1',
  page_index: 4,
  quote: 'Высота помещений в свету 2700 мм',
  norm_ref: null,
  note: null,
  catalog_version: 'v1',
  confirmed_by: '12345678-aaaa-bbbb-cccc-1234567890ab',
  confirmed_at: '2026-11-12T10:05:00Z',
  ...patch,
});

const question = (patch: Partial<DocQuestionOut> = {}): DocQuestionOut => ({
  code: 'clear_height',
  title: 'Высота помещения в свету',
  receiver_param: 'clear_height_mm',
  value_kind: 'length_mm',
  min_mm: 2000,
  max_mm: 6000,
  assumption: null,
  candidates: [],
  answers: [],
  ...patch,
});

const payload = (questions: DocQuestionOut[]): DocQuestionsOut => ({
  catalog_version: 'v1',
  questions,
  last_search: {
    job_id: 'j-1',
    status: 'succeeded',
    progress: 1,
    stage: null,
    error_code: null,
    created_at: '2026-11-12T10:00:00Z',
    finished_at: '2026-11-12T10:01:00Z',
    questions_found: 1,
    candidates: 3,
    revisions_total: 5,
    revisions_scanned: 4,
    revisions_no_text: 1,
    no_text_files: ['скан.pdf'],
    revisions_unreadable: 0,
    unreadable_files: [],
    versions: {},
  },
});

const mount = (questions: DocQuestionOut[]) => {
  vi.mocked(queries.useMeta).mockReturnValue({ isSuccess: true } as never);
  vi.mocked(queries.useFeatures).mockReturnValue({ 'project.consistency': true });
  vi.mocked(queries.useProject).mockReturnValue({ data: { name: 'Объект' } } as never);
  vi.mocked(client.getDocQuestions)
    .mockReset()
    .mockImplementation(() => ok(payload(questions)));
  vi.mocked(client.putDocAnswer)
    .mockReset()
    .mockImplementation(() => ok(answer()));
  vi.mocked(client.rejectDocCandidate)
    .mockReset()
    .mockImplementation(() => ok(candidate()));
  vi.mocked(client.removeDocAnswer)
    .mockReset()
    .mockImplementation(() => ok(undefined));
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <DocQuestionsScreen projectId="p-1" />
    </QueryClientProvider>,
  );
};

describe('экран «Вопросы к документации»', () => {
  beforeEach(() => vi.resetAllMocks());

  it('флаг закрыт — заглушка, вопросы не грузятся', () => {
    vi.mocked(queries.useMeta).mockReturnValue({ isSuccess: true } as never);
    vi.mocked(queries.useFeatures).mockReturnValue({ 'project.consistency': false });
    vi.mocked(queries.useProject).mockReturnValue({ data: { name: 'Объект' } } as never);
    render(
      <QueryClientProvider client={new QueryClient()}>
        <DocQuestionsScreen projectId="p-1" />
      </QueryClientProvider>,
    );
    expect(screen.getByText('Страница не найдена')).toBeInTheDocument();
    expect(client.getDocQuestions).not.toHaveBeenCalled();
  });

  it('строка: лучший кандидат с цитатой и ссылкой на лист; «ещё N вариантов»', async () => {
    mount([
      question({
        candidates: [
          candidate({
            id: 'c-low',
            score: 10,
            value_text: '2600 мм',
            value: {
              kind: 'length_mm',
              display: '2600',
              numbers: [2600],
              qualifier: null,
              code: null,
            },
          }),
          candidate(),
        ],
      }),
    ]);
    const row = within(await screen.findByTestId('doc-question'));
    expect(screen.getByTestId('search-result')).toHaveTextContent('1 из 1');
    expect(screen.getByText('Без текстового слоя: 1')).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Вопросы к документации' })).toBeInTheDocument();

    expect(row.getByText('Высота помещения в свету')).toBeInTheDocument();
    expect(row.getByText('clear_height_mm')).toBeInTheDocument();
    expect(row.getByText('2700')).toBeInTheDocument();
    expect(row.queryByText('2600')).toBeNull();
    expect(row.getByText('Высота помещений в свету 2700 мм')).toBeInTheDocument();
    expect(row.getByText(/АР_ПЗ\.pdf, стр\. 5/)).toBeInTheDocument();
    expect(row.getByRole('link', { name: 'Открыть лист' })).toHaveAttribute(
      'href',
      '/projects/p-1/workspace?revision=r-1&page=5',
    );
    expect(row.getByText('Других вариантов: 1')).toBeInTheDocument();
    expect(screen.queryByTestId('doc-candidate')).toBeNull();
  });

  it('подтверждённый ответ: значение, источник, область; «+ ещё N»', async () => {
    mount([
      question({
        answers: [answer({ source: 'manual' }), answer({ id: 'a-2', source: 'document' })],
      }),
    ]);
    const row = within(await screen.findByTestId('doc-question'));
    expect(row.getByText('Вручную')).toBeInTheDocument();
    expect(row.getByText('Область: корпус 9')).toBeInTheDocument();
    expect(row.getByText('Подтверждено')).toBeInTheDocument();
    expect(row.getByText('+ ещё 1')).toBeInTheDocument();
    expect(screen.queryByTestId('doc-answer')).toBeNull();
  });

  it('раскрытие показывает всех кандидатов, ответы и форму', async () => {
    mount([
      question({
        candidates: [
          candidate({ id: 'c-low', score: 10 }),
          candidate(),
          candidate({ id: 'c-rej', status: 'rejected' }),
        ],
        answers: [answer({ id: 'a-2', source: 'manual' })],
      }),
    ]);
    const toggle = await screen.findByRole('button', {
      name: 'Подробнее: Высота помещения в свету',
    });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');

    expect(screen.getAllByTestId('doc-candidate')).toHaveLength(3);
    const confirmed = within(screen.getByTestId('doc-answer'));
    expect(confirmed.getByText('Вручную')).toBeInTheDocument();
    expect(screen.getByText('Отклонённые (1)')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Ввести вручную' })).toBeInTheDocument();

    await userEvent.click(toggle);
    expect(screen.queryByTestId('doc-answer')).toBeNull();
  });

  it('«Принять» в строке шлёт source=document с candidate_id лучшего кандидата', async () => {
    mount([question({ candidates: [candidate({ id: 'c-low', score: 10 }), candidate()] })]);
    await userEvent.click(await screen.findByRole('button', { name: 'Принять' }));
    await waitFor(() => expect(client.putDocAnswer).toHaveBeenCalled());
    expect(vi.mocked(client.putDocAnswer).mock.calls[0]?.[0]).toMatchObject({
      path: { project_id: 'p-1', code: 'clear_height' },
      body: { source: 'document', candidate_id: 'c-1' },
    });
  });

  it('«Отклонить» в строке уходит на сервер; список перезапрашивается', async () => {
    mount([question({ candidates: [candidate()] })]);
    await userEvent.click(await screen.findByRole('button', { name: 'Отклонить' }));
    await waitFor(() => expect(client.rejectDocCandidate).toHaveBeenCalled());
    expect(vi.mocked(client.rejectDocCandidate).mock.calls[0]?.[0]).toMatchObject({
      path: { project_id: 'p-1', candidate_id: 'c-1' },
    });
    await waitFor(() => expect(client.getDocQuestions).toHaveBeenCalledTimes(2));
  });

  it('ошибка мутации показывается в строке', async () => {
    mount([question({ candidates: [candidate()] })]);
    vi.mocked(client.rejectDocCandidate).mockImplementation(
      () => Promise.reject(new Error('boom')) as never,
    );
    await userEvent.click(await screen.findByRole('button', { name: 'Отклонить' }));
    expect(await screen.findByRole('alert')).toBeInTheDocument();
  });

  it('ручной ответ без пояснения не отправляется; с пояснением — source=manual', async () => {
    mount([question()]);
    expect(await screen.findByText('В документации не найдено')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Ввести' }));
    await userEvent.click(screen.getByRole('button', { name: 'Ввести вручную' }));
    await userEvent.type(screen.getByLabelText('Значение, мм'), '2750');
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Укажите, откуда значение');
    expect(client.putDocAnswer).not.toHaveBeenCalled();

    await userEvent.type(screen.getByLabelText('Откуда значение'), 'разрез 1-1');
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
    await waitFor(() => expect(client.putDocAnswer).toHaveBeenCalled());
    expect(vi.mocked(client.putDocAnswer).mock.calls[0]?.[0]).toMatchObject({
      body: {
        source: 'manual',
        value: { numbers: [2750], code: null },
        note: 'разрез 1-1',
      },
    });
  });

  it('размер вне границ каталога не отправляется', async () => {
    mount([question()]);
    await userEvent.click(await screen.findByRole('button', { name: 'Ввести' }));
    await userEvent.click(screen.getByRole('button', { name: 'Ввести вручную' }));
    await userEvent.type(screen.getByLabelText('Значение, мм'), '10');
    await userEvent.type(screen.getByLabelText('Откуда значение'), 'расчёт');
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(screen.getByRole('alert')).toHaveTextContent('вне допустимых 2000–6000');
    expect(client.putDocAnswer).not.toHaveBeenCalled();
  });

  it('«Нет в проекте» — ответ словами, не 0; шлёт source=not_in_project', async () => {
    mount([
      question({ answers: [answer({ source: 'not_in_project', value: null, value_text: null })] }),
    ]);
    const row = within(await screen.findByTestId('doc-question'));
    expect(row.getAllByText('Нет в проекте').length).toBeGreaterThan(0);
    expect(row.queryByText('0')).toBeNull();

    await userEvent.click(screen.getByRole('button', { name: /^Подробнее/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Нет в проекте' }));
    await userEvent.click(screen.getByRole('button', { name: 'Подтвердить: нет в проекте' }));
    await waitFor(() => expect(client.putDocAnswer).toHaveBeenCalled());
    expect(vi.mocked(client.putDocAnswer).mock.calls[0]?.[0]).toMatchObject({
      body: { source: 'not_in_project' },
    });
  });

  it('нет кандидатов: «не найдено», норматив в строке; «Принять норматив» шлёт допущение', async () => {
    mount([
      question({
        assumption: {
          mm_from: 2500,
          mm_to: 2700,
          reference: 'СП 54, п. 5.3',
          status: 'draft',
          note: '',
        },
      }),
    ]);
    const row = within(await screen.findByTestId('doc-question'));
    expect(row.getByText('В документации не найдено')).toBeInTheDocument();
    expect(row.getByText('Норматив: 2500–2700 мм (допущение)')).toBeInTheDocument();
    await userEvent.click(row.getByRole('button', { name: 'Принять норматив' }));
    await waitFor(() => expect(client.putDocAnswer).toHaveBeenCalled());
    expect(vi.mocked(client.putDocAnswer).mock.calls[0]?.[0]).toMatchObject({
      body: { source: 'norm_assumption' },
    });
  });

  it('норматив в раскрытии — допущение с отдельной кнопкой', async () => {
    mount([
      question({
        assumption: {
          mm_from: 2500,
          mm_to: 2700,
          reference: 'СП 54, п. 5.3',
          status: 'draft',
          note: '',
        },
      }),
    ]);
    await userEvent.click(await screen.findByRole('button', { name: /^Подробнее/ }));
    const assumption = within(screen.getByTestId('doc-assumption'));
    expect(assumption.getByText('Допущение, не ответ проекта')).toBeInTheDocument();
    await userEvent.click(assumption.getByRole('button', { name: 'Принять норматив' }));
    await waitFor(() => expect(client.putDocAnswer).toHaveBeenCalled());
    expect(vi.mocked(client.putDocAnswer).mock.calls[0]?.[0]).toMatchObject({
      body: { source: 'norm_assumption' },
    });
  });

  it('удаление подтверждённого ответа из строки требует подтверждения', async () => {
    mount([question({ answers: [answer()] })]);
    const row = within(await screen.findByTestId('doc-question'));
    await userEvent.click(row.getByRole('button', { name: 'Удалить' }));
    expect(client.removeDocAnswer).not.toHaveBeenCalled();
    await userEvent.click(row.getByRole('button', { name: 'Подтвердить удаление ответа' }));
    await waitFor(() => expect(client.removeDocAnswer).toHaveBeenCalled());
    expect(vi.mocked(client.removeDocAnswer).mock.calls[0]?.[0]).toMatchObject({
      path: { project_id: 'p-1', answer_id: 'a-1' },
    });
  });
});
