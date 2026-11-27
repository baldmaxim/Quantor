import type * as ApiClient from '@quantor/api-client';
import type { CadScaleNeededItem, CadScaleNeededRead } from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ read: vi.fn() }));

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof ApiClient>()),
  readCadScaleNeeded: mocks.read,
}));

import { CadScaleNeededCard } from './CadScaleNeededCard';

const itemOf = (
  index: number,
  overrides: Partial<CadScaleNeededItem> = {},
): CadScaleNeededItem => ({
  document_id: 'doc-1',
  document_title: 'АР План.pdf',
  revision_id: 'rev-1',
  page_index: index,
  page_label: null,
  sheet_position: null,
  reason: 'auto_scale_unconfirmed',
  convert_job_id: `job-${index}`,
  view: null,
  ...overrides,
});

const dataOf = (items: CadScaleNeededItem[]): CadScaleNeededRead => ({
  total: items.length,
  items,
});

const renderCard = () =>
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <CadScaleNeededCard projectId="p-1" />
    </QueryClientProvider>,
  );

describe('CadScaleNeededCard', () => {
  beforeEach(() => {
    mocks.read.mockReset();
  });

  it('при total = 0 карточки нет', async () => {
    mocks.read.mockResolvedValue({ data: dataOf([]) });
    const { container } = renderCard();
    await vi.waitFor(() => expect(mocks.read).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('строка: лист, причина по-русски и ссылка на калибровку', async () => {
    mocks.read.mockResolvedValue({
      data: dataOf([
        itemOf(3, { reason: 'scale_missing', view: '1' }),
        itemOf(4, { page_label: 'План 2', reason: 'auto_scale_unconfirmed' }),
      ]),
    });
    renderCard();
    expect(await screen.findByText('Нужен масштаб: 2')).toBeInTheDocument();
    expect(screen.getByText('АР План.pdf · стр. 4')).toBeInTheDocument();
    expect(screen.getByText('АР План.pdf · План 2')).toBeInTheDocument();
    expect(screen.getByText('Нет масштаба для зон и трасс')).toBeInTheDocument();
    expect(screen.getByText('Автомасштаб не подтверждён')).toBeInTheDocument();
    const [first] = screen.getAllByRole('link', { name: 'Откалибровать' });
    const href = first?.getAttribute('href') ?? '';
    expect(href).toContain('/projects/p-1/workspace?');
    expect(href).toContain('revision=rev-1');
    expect(href).toContain('page=4');
    expect(href).toContain('job=job-3');
    expect(href).toContain('view=1');
  });

  it('первые 10, остальные по кнопке «Показать все»', async () => {
    mocks.read.mockResolvedValue({
      data: dataOf(Array.from({ length: 12 }, (_, index) => itemOf(index))),
    });
    renderCard();
    await screen.findByText('Нужен масштаб: 12');
    expect(screen.getAllByRole('link', { name: 'Откалибровать' })).toHaveLength(10);
    await userEvent.click(screen.getByRole('button', { name: 'Показать все (12)' }));
    expect(screen.getAllByRole('link', { name: 'Откалибровать' })).toHaveLength(12);
    expect(screen.queryByRole('button', { name: /Показать все/ })).toBeNull();
  });

  it('ошибка: сообщение и повтор', async () => {
    mocks.read.mockRejectedValueOnce(new Error('сеть'));
    mocks.read.mockResolvedValue({ data: dataOf([itemOf(0)]) });
    renderCard();
    expect(
      await screen.findByText('Не удалось получить список листов без масштаба'),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(await screen.findByText('Нужен масштаб: 1')).toBeInTheDocument();
  });
});
