import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  readCadFinishes: vi.fn(),
  listCadFinishTemplates: vi.fn(),
}));

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ...api,
}));

import { CadFinishPanel } from './CadFinishPanel';
import {
  finishZoneFixture,
  sheetFixture,
  templateFixture,
  wallsBreakdownFixture,
} from './finish-fixtures';

const renderPanel = (onActivate = vi.fn()) => {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <CadFinishPanel
        projectId="p1"
        revisionId="r1"
        pageIndex={0}
        load
        activeId={null}
        onActivate={onActivate}
      />
    </QueryClientProvider>,
  );
  return { onActivate };
};

describe('ведомость отделки листа', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.listCadFinishTemplates.mockResolvedValue({
      data: [templateFixture({ id: 't1', name: 'Черновая МОП' })],
    });
  });

  it('запрос по проекту, ревизии и странице; зона, итоги по слоям и по типам', async () => {
    api.readCadFinishes.mockResolvedValue({ data: sheetFixture() });
    renderPanel();
    const table = await screen.findByRole('table', { name: 'Зоны ведомости отделки' });
    expect(api.readCadFinishes.mock.calls[0]?.[0]).toMatchObject({
      path: { project_id: 'p1', revision_id: 'r1' },
      query: { page_index: 0 },
    });
    const row = within(table).getByText('Коридор', { selector: 'button' }).closest('tr');
    expect(row).not.toBeNull();
    const cells = within(row as HTMLElement).getAllByRole('cell');
    expect(cells[1]).toHaveTextContent('Коридор');
    expect(cells[2]).toHaveTextContent('Черновая МОП (по типу)');
    expect(cells[3]).toHaveTextContent('12,50');
    expect(cells[4]).toHaveTextContent('37,80');
    expect(cells[5]).toHaveTextContent('12,50');
    expect(cells[6]).toHaveTextContent('2 700');
    expect(cells[6]).toHaveTextContent('уровни листа');

    const byLayer = screen.getByRole('region', { name: 'Итоги по слоям' });
    expect(within(byLayer).getByText('Смесь М150')).toBeInTheDocument();
    expect(within(byLayer).getByText('1 125 кг')).toBeInTheDocument();
    const byType = screen.getByRole('region', { name: 'Итоги по типам помещений' });
    expect(within(byType).getByText('Коридор')).toBeInTheDocument();
  });

  it('не определено показывается «—», не 0', async () => {
    api.readCadFinishes.mockResolvedValue({
      data: sheetFixture({
        zones: [
          finishZoneFixture({
            template_id: null,
            template_source: null,
            floor_area_m2: null,
            wall_area_m2: null,
            ceiling_area_m2: null,
            wall_height_mm: null,
            wall_height_source: null,
            layers: [],
          }),
        ],
        totals: [
          {
            surface: 'walls',
            work: 'Штукатурка',
            material: null,
            material_unit: null,
            area_m2: null,
            material_qty: null,
            zone_count: 1,
            unknown_zone_count: 0,
            incomplete: false,
          },
        ],
      }),
    });
    renderPanel();
    const table = await screen.findByRole('table', { name: 'Зоны ведомости отделки' });
    const row = within(table).getByText('Коридор', { selector: 'button' }).closest('tr');
    const cells = within(row as HTMLElement).getAllByRole('cell');
    for (const index of [2, 3, 4, 5, 6]) expect(cells[index]).toHaveTextContent('—');
    for (const index of [3, 4, 5, 6]) expect(cells[index]).not.toHaveTextContent('0');
    const byLayer = screen.getByRole('region', { name: 'Итоги по слоям' });
    const cell = within(byLayer).getByText('Штукатурка').closest('tr') as HTMLElement;
    const values = within(cell).getAllByRole('cell');
    expect(values[2]).toHaveTextContent('—');
    expect(values[3]).toHaveTextContent('—');
    expect(values[4]).toHaveTextContent('—');
  });

  it('раскрытие строки показывает слои зоны', async () => {
    api.readCadFinishes.mockResolvedValue({ data: sheetFixture() });
    renderPanel();
    await screen.findByRole('table', { name: 'Зоны ведомости отделки' });
    expect(screen.queryByRole('table', { name: 'Слои зоны: Коридор' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Слои зоны: Коридор' }));
    const layers = screen.getByRole('table', { name: 'Слои зоны: Коридор' });
    expect(within(layers).getByText('Стяжка')).toBeInTheDocument();
    expect(within(layers).getByText('1 125 кг')).toBeInTheDocument();
  });

  it('раскрытие строки: «Стены по участкам» с разбивкой по основаниям, дверям, проёмам и откосам', async () => {
    api.readCadFinishes.mockResolvedValue({ data: sheetFixture() });
    renderPanel();
    await screen.findByRole('table', { name: 'Зоны ведомости отделки' });
    expect(screen.queryByText('Стены по участкам')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Слои зоны: Коридор' }));
    const block = screen.getByRole('table', { name: 'Участки стен зоны: Коридор' });
    const cellsOf = (label: string) =>
      within(within(block).getByText(label).closest('tr') as HTMLElement).getAllByRole('cell');
    expect(cellsOf('Монолит')[1]).toHaveTextContent('6,50');
    expect(cellsOf('Монолит')[2]).toHaveTextContent('17,55');
    expect(cellsOf('Кладка')[1]).toHaveTextContent('4,00');
    expect(cellsOf('Кладка')[2]).toHaveTextContent('10,80');
    expect(cellsOf('ГКЛ')[1]).toHaveTextContent('1,50');
    expect(cellsOf('ГКЛ')[2]).toHaveTextContent('4,05');
    expect(cellsOf('Двери (над проёмами)')[1]).toHaveTextContent('2,00');
    expect(cellsOf('Двери (над проёмами)')[2]).toHaveTextContent('0,90');
    expect(cellsOf('Проёмы без двери')[1]).toHaveTextContent('0,80');
    expect(cellsOf('Без стены')[1]).toHaveTextContent('0,30');
    expect(cellsOf('Откосы')[1]).toHaveTextContent('3,60');
    expect(cellsOf('Откосы')[2]).toHaveTextContent('0,54');
    expect(screen.queryByText('не привязано')).toBeNull();
  });

  it('не привязано: признак в таблице зон, в блоке - «по периметру», величин нет', async () => {
    api.readCadFinishes.mockResolvedValue({
      data: sheetFixture({
        zones: [
          finishZoneFixture({
            walls_breakdown: wallsBreakdownFixture({
              linked: false,
              monolith_m: null,
              masonry_m: null,
              gkl_m: null,
              door_m: null,
              gap_m: null,
              open_m: null,
              area_by_base: { monolith: null, masonry: null, gkl: null },
              door_over_area_m2: null,
              reveal_m: null,
              reveal_area_m2: null,
            }),
          }),
        ],
      }),
    });
    renderPanel();
    const table = await screen.findByRole('table', { name: 'Зоны ведомости отделки' });
    const row = within(table).getByText('Коридор', { selector: 'button' }).closest('tr');
    expect(within(row as HTMLElement).getAllByRole('cell')[4]).toHaveTextContent('не привязано');
    fireEvent.click(screen.getByRole('button', { name: 'Слои зоны: Коридор' }));
    expect(screen.getByText('по периметру (не привязано)')).toBeInTheDocument();
    expect(screen.queryByRole('table', { name: 'Участки стен зоны: Коридор' })).toBeNull();
  });

  it('привязано, но часть величин не определена - «—», не 0', async () => {
    api.readCadFinishes.mockResolvedValue({
      data: sheetFixture({
        zones: [
          finishZoneFixture({
            walls_breakdown: wallsBreakdownFixture({
              area_by_base: { monolith: null, masonry: null, gkl: null },
              door_over_area_m2: null,
              reveal_m: null,
              reveal_area_m2: null,
            }),
          }),
        ],
      }),
    });
    renderPanel();
    await screen.findByRole('table', { name: 'Зоны ведомости отделки' });
    fireEvent.click(screen.getByRole('button', { name: 'Слои зоны: Коридор' }));
    const block = screen.getByRole('table', { name: 'Участки стен зоны: Коридор' });
    const cells = (label: string) =>
      within(within(block).getByText(label).closest('tr') as HTMLElement).getAllByRole('cell');
    expect(cells('Монолит')[2]).toHaveTextContent('—');
    expect(cells('Двери (над проёмами)')[2]).toHaveTextContent('—');
    expect(cells('Откосы')[1]).toHaveTextContent('—');
    expect(cells('Откосы')[2]).toHaveTextContent('—');
    expect(cells('Монолит')[1]).toHaveTextContent('6,50');
  });

  it('предупреждение: подпись и ссылка на зону выделяет её на листе', async () => {
    api.readCadFinishes.mockResolvedValue({
      data: sheetFixture({
        warnings: [
          { code: 'windows_not_detected', zone_ids: [] },
          { code: 'wall_height_missing', zone_ids: ['z1'] },
        ],
      }),
    });
    const { onActivate } = renderPanel();
    expect(
      await screen.findByText(
        'Окна не распознаны: оконные участки наружных стен не отделываются целиком, подоконная часть не учтена',
      ),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Выделить зону: Коридор' }));
    expect(onActivate).toHaveBeenCalledWith('z1');
    fireEvent.click(screen.getByRole('button', { name: 'Показать на листе: Коридор' }));
    expect(onActivate).toHaveBeenCalledTimes(2);
  });

  it('ошибка чтения: текст и «Повторить»', async () => {
    api.readCadFinishes.mockRejectedValueOnce({ detail: { code: 'NOT_FOUND', message: 'x' } });
    api.readCadFinishes.mockResolvedValue({ data: sheetFixture() });
    renderPanel();
    expect(await screen.findByText(/Не удалось загрузить ведомость/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    await waitFor(() =>
      expect(screen.getByRole('table', { name: 'Зоны ведомости отделки' })).toBeInTheDocument(),
    );
  });
});
