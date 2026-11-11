import type * as ApiClient from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { MAX_VOR_BYTES } from '@/lib/cad/vor';
import { coverage, coverageGroup, LINKED_ITEM, vorDocument, vorItem } from '@/lib/cad/vor-fixtures';

const mocks = vi.hoisted(() => ({
  suggest: vi.fn(),
  items: vi.fn(),
  put: vi.fn(),
  docs: vi.fn(),
  links: vi.fn(),
  coverage: vi.fn(),
}));

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof ApiClient>()),
  suggestCadVorItems: mocks.suggest,
  listCadVorItems: mocks.items,
  putCadVorLinks: mocks.put,
  listCadVorDocuments: mocks.docs,
  listCadVorLinks: mocks.links,
  readCadVorCoverage: mocks.coverage,
}));

import { ConstructionsVor } from './ConstructionsVor';
import type { IWorkspaceCadVor } from './types';

const vorProps = (patch: Partial<IWorkspaceCadVor> = {}): IWorkspaceCadVor => ({
  projectId: 'p1',
  document: vorDocument(),
  coverage: coverage(),
  loading: false,
  uploading: false,
  deleting: false,
  error: null,
  onUpload: vi.fn(),
  onDelete: vi.fn(),
  showNotInVor: true,
  onShowNotInVorChange: vi.fn(),
  ...patch,
});

const mount = (ui: ReactNode) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
};

const SUGGESTED = vorItem({ id: 's1', code: '3.4', name: 'Перегородки 100 мм', quantity: 10, unit: 'м2' });
const FOUND = vorItem({ id: 'f1', name: 'Кладка перегородок из блоков', quantity: null });

beforeEach(() => {
  for (const mock of Object.values(mocks)) mock.mockReset();
  mocks.suggest.mockResolvedValue({ data: [{ item: SUGGESTED, score: 5, reasons: ['thickness', 'kind'] }] });
  mocks.items.mockResolvedValue({ data: { total: 1, items: [FOUND] } });
  mocks.put.mockResolvedValue({ data: [] });
  mocks.docs.mockResolvedValue({ data: [] });
  mocks.links.mockResolvedValue({ data: [] });
  mocks.coverage.mockResolvedValue({ data: coverage() });
});

describe('блок «ВОР Заказчика»', () => {
  it('нет ВОР: кнопка загрузки и пояснение, групп нет', () => {
    mount(<ConstructionsVor vor={vorProps({ document: null, coverage: null })} />);
    expect(screen.getByRole('button', { name: 'Загрузить ВОР Заказчика (.xlsx)' })).toBeInTheDocument();
    expect(screen.getByText('ВОР — только для сверки, на расчёт не влияет.')).toBeInTheDocument();
    expect(screen.queryByTestId('vor-group')).toBeNull();
  });

  it('есть ВОР: имя файла, строк, дата, «Заменить» и «Удалить» с подтверждением', () => {
    const p = vorProps();
    mount(<ConstructionsVor vor={p} />);
    expect(screen.getByText('ВОР.xlsx')).toBeInTheDocument();
    expect(screen.getByText(/строк: 42/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Заменить' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Удалить' }));
    expect(p.onDelete).not.toHaveBeenCalled();
    const dialog = screen.getByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Удалить' }));
    expect(p.onDelete).toHaveBeenCalledTimes(1);
  });

  it('группы: «в ВОР» со строкой и количеством справочно, «не в ВОР» заметно; разницы нет', () => {
    mount(<ConstructionsVor vor={vorProps()} />);
    const [linked, missing] = screen.getAllByTestId('vor-group');
    expect(linked).toHaveAttribute('data-status', 'linked');
    expect(linked).toHaveTextContent('в ВОР');
    expect(linked).toHaveTextContent('2.1 — Кладка газобетон 100 мм');
    expect(linked).toHaveTextContent('55 м3 (по ВОР, на весь объект)');
    expect(missing).toHaveAttribute('data-status', 'not_in_vor');
    expect(within(missing as HTMLElement).getByText('не в ВОР')).toHaveClass('text-danger');
    expect(within(missing as HTMLElement).getByRole('button', { name: 'Сопоставить' })).toBeInTheDocument();
    // Количества CAD и ВОР не сравниваются: ни разницы, ни расхождения, ни процентов.
    expect(screen.queryByText(/разниц|расхожд|отклонени|%/i)).toBeNull();
  });

  it('толщины: которых нет в ВОР и толщины в ВОР', () => {
    mount(<ConstructionsVor vor={vorProps({ coverage: coverage({ thickness_not_in_vor: ['masonry|80|', 'masonry|150|'] }) })} />);
    expect(screen.getByText('Толщины, которых нет в ВОР: 80, 150 мм')).toBeInTheDocument();
    expect(screen.getByText('Толщины в ВОР: 120, 200 мм')).toBeInTheDocument();
  });

  it('переключатель «Не в ВОР» меняет подсветку', () => {
    const p = vorProps();
    mount(<ConstructionsVor vor={p} />);
    fireEvent.click(screen.getByRole('checkbox', { name: 'Не в ВОР' }));
    expect(p.onShowNotInVorChange).toHaveBeenCalledWith(false);
  });

  it('файл больше 20 МБ: понятная ошибка, на сервер не уходит', () => {
    const p = vorProps({ document: null, coverage: null });
    mount(<ConstructionsVor vor={p} />);
    const big = new File(['x'], 'ВОР.xlsx');
    Object.defineProperty(big, 'size', { value: MAX_VOR_BYTES + 1 });
    fireEvent.change(screen.getByLabelText('Файл ВОР Заказчика'), { target: { files: [big] } });
    expect(screen.getByRole('alert')).toHaveTextContent('Файл больше 20 МБ');
    expect(p.onUpload).not.toHaveBeenCalled();
  });

  it('подходящий файл передаётся на загрузку', () => {
    const p = vorProps({ document: null, coverage: null });
    mount(<ConstructionsVor vor={p} />);
    const ok = new File(['x'], 'ВОР.xlsx');
    fireEvent.change(screen.getByLabelText('Файл ВОР Заказчика'), { target: { files: [ok] } });
    expect(p.onUpload).toHaveBeenCalledWith(ok);
  });
});

describe('диалог сопоставления', () => {
  const open = () => {
    mount(<ConstructionsVor vor={vorProps()} />);
    const [, missing] = screen.getAllByTestId('vor-group');
    fireEvent.click(within(missing as HTMLElement).getByRole('button', { name: 'Сопоставить' }));
  };

  it('подсказки с причинами; выбор подсказки и найденной строки - PUT с group_key и id', async () => {
    open();
    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByText('3.4 — Перегородки 100 мм')).toBeInTheDocument();
    expect(within(dialog).getByText(/совпала толщина, совпал вид/)).toBeInTheDocument();
    expect(mocks.suggest).toHaveBeenCalledWith(
      expect.objectContaining({ query: { group_key: 'masonry|100|', document_id: 'd1' } }),
    );

    fireEvent.click(within(dialog).getByRole('checkbox', { name: /Перегородки 100 мм/ }));
    fireEvent.click(await within(dialog).findByRole('checkbox', { name: /Кладка перегородок/ }));
    expect(within(dialog).getByText('Выбрано строк: 2')).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }));

    await waitFor(() =>
      expect(mocks.put).toHaveBeenCalledWith({
        throwOnError: true,
        path: { project_id: 'p1', group_key: 'masonry|100|' },
        body: { vor_item_ids: ['s1', 'f1'] },
      }),
    );
  });

  it('поиск по наименованию и фильтр по толщине уходят в запрос строк', async () => {
    open();
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Поиск по наименованию'), { target: { value: 'перегородки' } });
    fireEvent.change(within(dialog).getByLabelText('Толщина, мм'), { target: { value: '100' } });
    await waitFor(() =>
      expect(mocks.items).toHaveBeenLastCalledWith(
        expect.objectContaining({
          path: { project_id: 'p1', document_id: 'd1' },
          query: expect.objectContaining({ q: 'перегородки', thickness: 100 }),
        }),
      ),
    );
  });

  it('«Отвязать всё»: PUT с пустым набором', async () => {
    mount(<ConstructionsVor vor={vorProps()} />);
    const [linked] = screen.getAllByTestId('vor-group');
    fireEvent.click(within(linked as HTMLElement).getByRole('button', { name: 'Сопоставить' }));
    const dialog = await screen.findByRole('dialog');
    // Прежняя связь группы выбрана заранее.
    expect(within(dialog).getByText('Выбрано строк: 1')).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Отвязать всё' }));
    await waitFor(() =>
      expect(mocks.put).toHaveBeenCalledWith({
        throwOnError: true,
        path: { project_id: 'p1', group_key: 'masonry|120|' },
        body: { vor_item_ids: [] },
      }),
    );
  });
});

describe('группа с несколькими строками', () => {
  it('каждая строка показана с кодом и количеством справочно', () => {
    const second = vorItem({ id: 'i2', name: 'Кладка 2', quantity: 7, unit: 'м3' });
    mount(
      <ConstructionsVor
        vor={vorProps({
          coverage: coverage({
            groups: [coverageGroup({ status: 'linked', items: [LINKED_ITEM, second] })],
          }),
        })}
      />,
    );
    expect(screen.getAllByText(/по ВОР, на весь объект/)).toHaveLength(2);
  });
});
