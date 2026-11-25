import { readCadAiReviews, startCadAiReview, type AiReviewState } from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';

import { CadAiReviewPanel } from './CadAiReviewPanel';

vi.mock('@quantor/api-client', () => ({
  readCadAiReviews: vi.fn(),
  startCadAiReview: vi.fn(),
}));
vi.mock('@/lib/queries', () => ({
  unwrap: (response: { data: unknown }) => response.data,
}));

const transport = () => ({ request: new Request('http://localhost'), response: new Response() });

const state: AiReviewState = {
  available: true,
  max_iterations: 3,
  reviews: [
    {
      job_id: 'review-1',
      status: 'succeeded',
      error_message: null,
      result: {
        walls_job_id: 'job-1',
        walls_attempt: 1,
        cad_job_id: 'cad-1',
        revision_id: 'revision',
        page_index: 81,
        view: 1,
        role: 'verifier',
        iteration: 1,
        model: 'claude-opus-5-5',
        input_sha256: 'pdf',
        walls_sha256: 'walls',
        dxf_sha256: 'dxf',
        prompt_sha256: 'prompt',
        bundle_sha256: 'bundle',
        sources: {},
        usage: { cost_usd: 1.234, duration_ms: 61000, input_tokens: 10, output_tokens: 5 },
        render: { clip: [0, 0, 100, 100], zoom: 2 },
        remark_keys: ['ai-1'],
        report: {
          verdict: 'needs_correction',
          findings: [
            {
              type: 'missing_wall',
              priority: 'major',
              bbox_px: [1, 2, 3, 4],
              construction_ids: ['c1'],
              observation: 'Нет контура у оси 3',
              evidence: 'Лист 32',
              suggested_fix: 'Достроить контур',
            },
          ],
          props: [{ construction_id: 'c7', thickness_mm: 200, evidence: 'Номинал проекта' }],
          vor_check: [
            {
              vor_ref: '3.1',
              name: 'Кладка 120',
              status: 'absent_on_view',
              construction_ids: [],
              note: '',
            },
          ],
          limitations: [],
        },
      },
    },
  ],
};

const renderPanel = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CadAiReviewPanel wallsJobId="job-1" />
    </QueryClientProvider>,
  );
};

beforeEach(() => {
  vi.clearAllMocks();
});

it('shows the last review: findings, property suggestions, VOR check and cost', async () => {
  vi.mocked(readCadAiReviews).mockResolvedValue({
    ...transport(),
    data: state,
  } as Awaited<ReturnType<typeof readCadAiReviews>>);
  renderPanel();
  const region = await screen.findByRole('region', { name: 'ИИ-проверка вида' });
  expect(within(region).getByRole('status')).toHaveTextContent('Требуются исправления');
  expect(within(region).getByText(/Круг 1 из 3/)).toBeInTheDocument();
  expect(within(region).getByText(/Нет стены/)).toBeInTheDocument();
  expect(within(region).getByText('Нет контура у оси 3')).toBeInTheDocument();
  expect(within(region).getByText('c7')).toBeInTheDocument();
  expect(within(region).getByText(/толщина: 200 мм/)).toBeInTheDocument();
  expect(within(region).getByText(/Нет на виде/)).toBeInTheDocument();
  expect(within(region).getByText(/1\.23 \$/)).toBeInTheDocument();
});

it('starts the corrector and verifier roles', async () => {
  vi.mocked(readCadAiReviews).mockResolvedValue({
    ...transport(),
    data: { available: true, max_iterations: 3, reviews: [] },
  } as Awaited<ReturnType<typeof readCadAiReviews>>);
  vi.mocked(startCadAiReview).mockResolvedValue({
    ...transport(),
    data: { job_id: 'review-2', status: 'queued', error_message: null },
  } as Awaited<ReturnType<typeof startCadAiReview>>);
  renderPanel();
  await userEvent.click(await screen.findByRole('button', { name: 'ИИ-правка' }));
  await waitFor(() => expect(startCadAiReview).toHaveBeenCalledTimes(1));
  expect(vi.mocked(startCadAiReview).mock.calls[0]?.[0]).toMatchObject({
    path: { job_id: 'job-1' },
    body: { role: 'corrector' },
  });
  await userEvent.click(screen.getByRole('button', { name: 'ИИ-проверка' }));
  await waitFor(() => expect(startCadAiReview).toHaveBeenCalledTimes(2));
  expect(vi.mocked(startCadAiReview).mock.calls[1]?.[0]).toMatchObject({
    body: { role: 'verifier' },
  });
});

it('disables the buttons when the round limit is exhausted', async () => {
  vi.mocked(readCadAiReviews).mockResolvedValue({
    ...transport(),
    data: { ...state, max_iterations: 1 },
  } as Awaited<ReturnType<typeof readCadAiReviews>>);
  renderPanel();
  expect(await screen.findByRole('button', { name: 'ИИ-правка' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'ИИ-проверка' })).toBeDisabled();
});

it('renders nothing when unavailable and there are no reviews', async () => {
  vi.mocked(readCadAiReviews).mockResolvedValue({
    ...transport(),
    data: { available: false, max_iterations: 0, reviews: [] },
  } as Awaited<ReturnType<typeof readCadAiReviews>>);
  const { container } = renderPanel();
  await waitFor(() => expect(readCadAiReviews).toHaveBeenCalled());
  expect(container).toBeEmptyDOMElement();
});
