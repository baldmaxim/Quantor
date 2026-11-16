import * as client from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useCanEditSitePins } from './site-pin-queries';

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof client>()),
  readSession: vi.fn(),
  readMeta: vi.fn(),
}));

const setup = (permissions: string[], features: Record<string, boolean>) => {
  vi.mocked(client.readSession).mockResolvedValue({ data: { permissions } } as never);
  vi.mocked(client.readMeta).mockResolvedValue({ data: { features } } as never);
};

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {children}
  </QueryClientProvider>
);

describe('право на ручную привязку', () => {
  beforeEach(() => vi.clearAllMocks());

  it('нужны и флаг cad.export, и право записи document.upload', async () => {
    setup(['document.upload'], { 'cad.export': true });
    const { result } = renderHook(() => useCanEditSitePins(), { wrapper });
    await waitFor(() => expect(result.current).toBe(true));
  });

  it('права записи нет - нет', async () => {
    setup(['document.read'], { 'cad.export': true });
    const { result } = renderHook(() => useCanEditSitePins(), { wrapper });
    await waitFor(() => expect(client.readSession).toHaveBeenCalled());
    await waitFor(() => expect(client.readMeta).toHaveBeenCalled());
    expect(result.current).toBe(false);
  });

  it('флаг выключен - нет, даже с правом записи', async () => {
    setup(['document.upload'], { 'cad.export': false });
    const { result } = renderHook(() => useCanEditSitePins(), { wrapper });
    await waitFor(() => expect(client.readMeta).toHaveBeenCalled());
    expect(result.current).toBe(false);
  });
});
