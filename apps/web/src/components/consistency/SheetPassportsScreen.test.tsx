import * as queries from '@/lib/queries';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { SheetPassportsScreen } from './SheetPassportsScreen';

vi.mock('@/lib/queries', async (importOriginal) => ({
  ...(await importOriginal<typeof queries>()),
  useMeta: vi.fn(),
  useFeatures: vi.fn(),
  useProject: vi.fn(),
}));

vi.mock('./SheetPassportsView', () => ({
  SheetPassportsView: () => <div data-testid="passports-view" />,
}));

const setup = (loaded: boolean, features: Record<string, boolean>) => {
  vi.mocked(queries.useMeta).mockReturnValue({ isSuccess: loaded } as never);
  vi.mocked(queries.useFeatures).mockReturnValue(features);
  vi.mocked(queries.useProject).mockReturnValue({ data: { name: 'Объект' } } as never);
  render(
    <QueryClientProvider client={new QueryClient()}>
      <SheetPassportsScreen projectId="p-1" />
    </QueryClientProvider>,
  );
};

describe('экран «Листы комплекта»', () => {
  beforeEach(() => vi.resetAllMocks());

  it('флаг закрыт — заглушка, таблицы нет', () => {
    setup(true, { 'project.consistency': false });
    expect(screen.getByText('Страница не найдена')).toBeInTheDocument();
    expect(screen.queryByTestId('passports-view')).toBeNull();
  });

  it('пока мета не пришла — ни таблицы, ни «не найдено»', () => {
    setup(false, {});
    expect(screen.queryByText('Страница не найдена')).toBeNull();
    expect(screen.queryByTestId('passports-view')).toBeNull();
  });

  it('флаг открыт — таблица и крошка', () => {
    setup(true, { 'project.consistency': true });
    expect(screen.getByTestId('passports-view')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Листы комплекта' })).toBeInTheDocument();
  });
});
