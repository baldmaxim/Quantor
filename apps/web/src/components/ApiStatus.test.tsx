import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiStatus } from './ApiStatus';

vi.mock('@quantor/api-client', () => ({
  readMeta: vi.fn(),
}));

const { readMeta } = await import('@quantor/api-client');
const readMetaMock = vi.mocked(readMeta);

const renderWithQuery = (ui: ReactNode) => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
};

afterEach(() => {
  vi.resetAllMocks();
});

describe('ApiStatus', () => {
  it('показывает версии контракта, когда API отвечает', async () => {
    readMetaMock.mockResolvedValue({
      data: {
        api_version: 'v1',
        schema_version: 1,
        environment: 'local',
        stage: 'stage-1',
        features: { projects: true },
      },
      error: undefined,
      request: new Request('http://localhost/api/v1/meta'),
      response: new Response(null, { status: 200 }),
    });

    renderWithQuery(<ApiStatus />);

    expect(await screen.findByText('stage-1')).toBeInTheDocument();
    expect(screen.getByText('v1')).toBeInTheDocument();
  });

  it('сообщает о недоступности API вместо пустого экрана', async () => {
    readMetaMock.mockRejectedValue(new Error('connection refused'));

    renderWithQuery(<ApiStatus />);

    expect(await screen.findByText(/API недоступен/)).toBeInTheDocument();
  });
});
