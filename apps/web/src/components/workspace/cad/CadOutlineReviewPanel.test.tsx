import { readCadOutlineReviews, type OutlineReviewRead } from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import { expect, it, vi } from 'vitest';

import { CadOutlineReviewPanel } from './CadOutlineReviewPanel';

vi.mock('@quantor/api-client', () => ({ readCadOutlineReviews: vi.fn() }));
vi.mock('@/lib/queries', () => ({
  unwrap: (response: { data: OutlineReviewRead[] }) => response.data,
}));

it('shows the report and source links for the walls job of the selected view', async () => {
  vi.mocked(readCadOutlineReviews).mockImplementation(async (
    options,
  ): Promise<{ data: OutlineReviewRead[]; request: Request; response: Response }> => {
    const transport = { request: new Request('http://localhost'), response: new Response() };
    if (options.path.job_id === 'job-14') {
      return {
        ...transport,
        data: [{
          job_id: 'review-14',
          status: 'succeeded',
          error_message: null,
          result: {
            building: 9,
            section: 3,
            view: 1,
            floor: 14,
            pdf_page: 81,
            generator: 'cad_walls.v1.15',
            revision_id: 'revision',
            input_sha256: 'pdf',
            dxf_sha256: 'dxf',
            walls_sha256: 'walls',
            walls_job_id: 'job-14',
            walls_attempt: 1,
            zones_count: 52,
            sources: {},
            report: {
              verdict: 'needs_correction',
              findings: [{
                priority: 'major', location: 'Ось 3', observation: 'Расхождение',
                evidence: 'Лист 32', suggested_fix: 'Сверить контур',
              }],
              sources: [
                { role: 'project', applicability: 'applicable',
                  reference: 'АР, лист 32', observation: 'План 14-го этажа' },
                { role: 'explanatory_note', applicability: 'applicable',
                  reference: 'ПЗ, раздел 3', observation: 'Этажность' },
                { role: 'terms_of_reference', applicability: 'applicable',
                  reference: 'ТЗ, часть 4', observation: 'Материал стен' },
                { role: 'contract', applicability: 'applicable',
                  reference: 'Договор, п. 13.17', observation: 'Объём работ' },
              ],
              limitations: [],
            },
          },
        }],
      };
    }
    return { ...transport, data: [{ job_id: 'review-15', status: 'running', error_message: null }] };
  });
  const client = new QueryClient();
  const panel = (wallsJobId: string) => (
    <QueryClientProvider client={client}>
      <CadOutlineReviewPanel wallsJobId={wallsJobId} />
    </QueryClientProvider>
  );
  const { rerender, unmount } = render(panel('job-14'));
  const region = await screen.findByRole('region', { name: 'Проверка обводки Codex' });
  expect(within(region).getByRole('status')).toHaveTextContent('Требуются исправления');
  expect(within(region).getByText(/Ось 3/)).toBeInTheDocument();
  expect(within(region).getAllByRole('link')).toHaveLength(4);
  expect(within(region).getByRole('link', { name: 'Проект' })).toHaveAttribute(
    'href', expect.stringContaining('/jobs/review-14/cad-outline-source/project'),
  );
  rerender(panel('job-15'));
  expect(await screen.findByText('Проверка идёт')).toBeInTheDocument();
  expect(screen.queryByText(/Ось 3/)).toBeNull();
  unmount();
  client.clear();
});
