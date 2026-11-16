import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  readCadFinishes: vi.fn(),
  listCadFinishTemplates: vi.fn(),
}));

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ...api,
}));

import { CadFinishPanel, type ICadFinishPanelProps } from './CadFinishPanel';
import { finishZoneFixture, sheetFixture, templateFixture } from './finish-fixtures';

const renderPanel = (patch: Partial<ICadFinishPanelProps> = {}) => {
  const onActivate = vi.fn();
  const onOpenTab = vi.fn();
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
        onOpenTab={onOpenTab}
        {...patch}
      />
    </QueryClientProvider>,
  );
  return { onActivate, onOpenTab };
};

const step = (number: number): HTMLElement =>
  screen.getByRole('region', { name: new RegExp(`^Шаг ${number}\\.`) });

const ready = async (): Promise<void> => {
  await screen.findByRole('table', { name: 'Зоны ведомости отделки' });
  await screen.findByText(/^Шаблонов: \d/);
};

describe('раздел «Отделка»: чек-лист шагов', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.listCadFinishTemplates.mockResolvedValue({ data: [templateFixture()] });
    api.readCadFinishes.mockResolvedValue({ data: sheetFixture() });
  });

  it('раздел не открыт: запросов нет, шаги нейтральны, чисел нет', () => {
    renderPanel({ load: false });
    expect(api.readCadFinishes).not.toHaveBeenCalled();
    expect(api.listCadFinishTemplates).not.toHaveBeenCalled();
    for (const number of [1, 2, 3, 4]) {
      expect(step(number)).toHaveAttribute('data-status', 'neutral');
      expect(within(step(number)).getByText('нет данных')).toBeInTheDocument();
    }
    expect(within(step(1)).getByText('Помещений на листе: —')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Открыть «Зоны»' })).toBeNull();
  });

  it('всё готово: четыре «готово», шаблоны свёрнуты, кнопок перехода нет', async () => {
    renderPanel();
    await ready();
    for (const number of [1, 2, 3, 4]) {
      expect(step(number)).toHaveAttribute('data-status', 'ready');
    }
    expect(within(step(1)).getByText('Помещений на листе: 1 · без типа: 0')).toBeInTheDocument();
    expect(
      within(step(3)).getByText('С шаблоном: 1 из 1 (по типу: 1, явно: 0)'),
    ).toBeInTheDocument();
    const details = within(step(2)).getByText('Показать шаблоны').closest('details');
    expect(details).not.toHaveAttribute('open');
    expect(screen.queryByRole('button', { name: 'Открыть «Зоны»' })).toBeNull();
    expect(
      within(step(4)).getByText('Рабочая таблица пилота: не ВОР и не смета. Стоимости нет.'),
    ).toBeInTheDocument();
  });

  it('правка шаблона из свёрнутого списка: редактор виден', async () => {
    renderPanel();
    await ready();
    fireEvent.click(screen.getByRole('button', { name: 'Изменить шаблон: Черновая МОП' }));
    expect(within(step(2)).queryByText('Показать шаблоны')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Изменить шаблон: Черновая МОП' })).toBeNull();
  });

  it('зона без типа и без шаблона: ссылки в шагах 1 и 3, переход в «Зоны», no_template не дублируется', async () => {
    api.readCadFinishes.mockResolvedValue({
      data: sheetFixture({
        zones: [
          finishZoneFixture(),
          finishZoneFixture({
            zone_id: 'z2',
            name: 'Холл',
            room_type: null,
            template_id: null,
            template_source: null,
          }),
        ],
        warnings: [{ code: 'no_template', zone_ids: ['z2'] }],
      }),
    });
    const { onActivate, onOpenTab } = renderPanel();
    await ready();
    expect(step(1)).toHaveAttribute('data-status', 'action');
    expect(
      within(step(1)).getByText('Задайте тип помещения — по нему подбирается шаблон'),
    ).toBeInTheDocument();
    fireEvent.click(within(step(1)).getByRole('button', { name: 'Выделить зону: Холл' }));
    expect(onActivate).toHaveBeenLastCalledWith('z2');
    fireEvent.click(within(step(1)).getByRole('button', { name: 'Открыть «Зоны»' }));
    expect(onOpenTab).toHaveBeenLastCalledWith('zones');

    expect(step(3)).toHaveAttribute('data-status', 'action');
    expect(
      within(step(3)).getByText('С шаблоном: 1 из 2 (по типу: 1, явно: 0)'),
    ).toBeInTheDocument();
    expect(within(step(3)).getByRole('button', { name: 'Выделить зону: Холл' })).toBeVisible();
    fireEvent.click(within(step(3)).getByRole('button', { name: 'Открыть «Зоны»' }));
    expect(onOpenTab).toHaveBeenCalledTimes(2);

    expect(step(4)).toHaveAttribute('data-status', 'action');
    expect(screen.queryByText(/Не назначен шаблон отделки/)).toBeNull();
    expect(screen.queryByRole('region', { name: 'Предупреждения ведомости' })).toBeNull();
  });

  it('без onOpenTab кнопок перехода нет', async () => {
    api.readCadFinishes.mockResolvedValue({
      data: sheetFixture({
        zones: [],
        totals: [],
        by_room_type: [],
        warnings: [{ code: 'wall_height_missing', zone_ids: [] }],
      }),
    });
    renderPanel({ onOpenTab: undefined });
    expect(
      await screen.findByText('На листе нет зон-помещений: разметьте их в разделе «Зоны»'),
    ).toBeInTheDocument();
    expect(step(1)).toHaveAttribute('data-status', 'action');
    expect(await screen.findByText(/Не определена высота стен/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Открыть «Зоны»' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Открыть «Конструкции»' })).toBeNull();
  });

  it('шаблонов нет: шаг 2 требует действия, список не свёрнут', async () => {
    api.listCadFinishTemplates.mockResolvedValue({ data: [] });
    renderPanel();
    await ready();
    expect(step(2)).toHaveAttribute('data-status', 'action');
    expect(
      within(step(2)).getByText('Создайте шаблон: слои пола, стен и потолка для типа помещения'),
    ).toBeInTheDocument();
    expect(within(step(2)).getByRole('button', { name: 'Новый шаблон' })).toBeVisible();
  });

  it('высота стен: предупреждение в шаге 4 с переходом в «Конструкции»', async () => {
    api.readCadFinishes.mockResolvedValue({
      data: sheetFixture({ warnings: [{ code: 'wall_height_missing', zone_ids: ['z1'] }] }),
    });
    const { onOpenTab } = renderPanel();
    await ready();
    expect(step(4)).toHaveAttribute('data-status', 'action');
    fireEvent.click(within(step(4)).getByRole('button', { name: 'Открыть «Конструкции»' }));
    expect(onOpenTab).toHaveBeenCalledWith('constructions');
  });

  it('нет калибровки: плашка над шагами, в предупреждениях шага 4 её нет', async () => {
    api.readCadFinishes.mockResolvedValue({
      data: sheetFixture({ warnings: [{ code: 'calibration_missing', zone_ids: ['z1'] }] }),
    });
    const { onActivate } = renderPanel();
    await ready();
    const banner = screen.getByRole('alert');
    expect(banner).toHaveTextContent('Нет калибровки масштаба: площади не определены (зон: 1)');
    expect(banner.compareDocumentPosition(step(1)) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    fireEvent.click(within(banner).getByRole('button', { name: 'Выделить зону: Коридор' }));
    expect(onActivate).toHaveBeenCalledWith('z1');
    expect(screen.queryByRole('region', { name: 'Предупреждения ведомости' })).toBeNull();
    expect(step(4)).toHaveAttribute('data-status', 'action');
  });
});
