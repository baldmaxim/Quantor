import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { construction, constructionsRead } from '@/lib/cad/constructions-fixtures';

import { coverage, vorDocument } from '@/lib/cad/vor-fixtures';

import { ConstructionsPanel } from './ConstructionsPanel';
import type { IWorkspaceCadConstructions } from './types';

const base = construction({ id: 'a' });
const check = construction({
  id: 'c',
  thickness_nominal_mm: null,
  computed: { ...base.computed, status: 'thickness_check', thickness_mm: null },
});
const noHeight = construction({
  id: 'h',
  computed: { ...base.computed, status: 'height_missing', height_mm: null },
});
const pylon = construction({
  id: 'p',
  kind: 'monolith_pylon',
  thickness_nominal_mm: 300,
  computed: { ...base.computed, thickness_mm: 300 },
});

const DATA = constructionsRead({
  constructions: [base, construction({ id: 'b' }), check, noHeight, pylon],
  totals: [
    { kind: 'masonry', thickness_mm: 120, material: null, count: 2, length_m: 10, wall_area_m2: 27, volume_m3: 3.24 },
    { kind: 'monolith_pylon', thickness_mm: 300, material: 'monolith_concrete', count: 1, length_m: 1, wall_area_m2: 2.7, volume_m3: 0.81 },
  ],
  summary: {
    total_count: 5,
    thickness_check_count: 1,
    height_missing_count: 1,
    unaccounted_gap_openings: 2,
    door_openings_without_host: 3,
  },
});

const props = (patch: Partial<IWorkspaceCadConstructions> = {}): IWorkspaceCadConstructions => ({
  status: 'ready',
  data: DATA,
  notReadyText: null,
  loadError: null,
  onReload: vi.fn(),
  calculating: false,
  actionError: null,
  onCompute: vi.fn(),
  levelsSaving: false,
  onSaveLevels: vi.fn(),
  activeGroup: null,
  onSelectGroup: vi.fn(),
  ...patch,
});

describe('ConstructionsPanel: нет результата', () => {
  it('404: текст по статусу и кнопка «Посчитать конструкции»', () => {
    const p = props({ status: 'not-ready', data: null, notReadyText: 'Конструкции этого листа ещё не считались.' });
    render(<ConstructionsPanel {...p} />);
    expect(screen.getByText('Конструкции этого листа ещё не считались.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Посчитать конструкции' }));
    expect(p.onCompute).toHaveBeenCalledTimes(1);
  });

  it('расчёт идёт: статус вместо подсказки, кнопка недоступна', () => {
    render(
      <ConstructionsPanel
        {...props({ status: 'not-ready', data: null, notReadyText: 'старый текст', calculating: true })}
      />,
    );
    expect(screen.getByRole('status')).toHaveTextContent('Конструкции считаются');
    expect(screen.queryByText('старый текст')).toBeNull();
    expect(screen.getByRole('button', { name: 'Посчитать конструкции' })).toBeDisabled();
  });

  it('отказ запуска показан текстом', () => {
    render(
      <ConstructionsPanel
        {...props({
          status: 'not-ready',
          data: null,
          actionError: 'Конструкции этого вида уже считаются.',
        })}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('уже считаются');
  });

  it('загрузка - скелетон, отказ чтения - текст и «Повторить»', () => {
    const { unmount } = render(<ConstructionsPanel {...props({ status: 'loading', data: null })} />);
    expect(screen.getByRole('status', { name: 'Загрузка конструкций' })).toBeInTheDocument();
    unmount();
    const p = props({ status: 'error', data: null, loadError: 'нет связи' });
    render(<ConstructionsPanel {...p} />);
    expect(screen.getByRole('alert')).toHaveTextContent('Не удалось загрузить конструкции. нет связи');
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(p.onReload).toHaveBeenCalled();
  });
});

describe('ConstructionsPanel: свод', () => {
  it('группы: вид, толщина, материал («не задан»), число, длина, стена, объём; итоги кладки и монолита отдельно', () => {
    render(<ConstructionsPanel {...props()} />);
    const table = screen.getByRole('table');
    const rows = within(table).getAllByRole('row');
    expect(within(rows[1] as HTMLElement).getAllByRole('cell').map((cell) => cell.textContent)).toEqual([
      'Кладка',
      '120',
      'не задан',
      '2',
      '10',
      '27',
      '3,24',
    ]);
    expect(within(rows[2] as HTMLElement).getByText('Монолитный железобетон')).toBeInTheDocument();
    expect(within(table).getByText('Итого кладка').closest('tr')).toHaveTextContent('3,24');
    expect(within(table).getByText('Итого монолит').closest('tr')).toHaveTextContent('0,81');
  });

  it('строка группы подсвечивает её конструкции на холсте', () => {
    const p = props();
    render(<ConstructionsPanel {...p} />);
    fireEvent.click(screen.getByRole('button', { name: 'Кладка' }));
    expect(p.onSelectGroup).toHaveBeenCalledWith('masonry|120|', ['a', 'b']);
  });

  it('отдельные строки: толщина не определена, нет высоты, проёмы без данных, двери без стены', () => {
    const p = props();
    render(<ConstructionsPanel {...p} />);
    fireEvent.click(screen.getByRole('button', { name: 'Толщина не определена — 1' }));
    expect(p.onSelectGroup).toHaveBeenCalledWith('status:thickness_check', ['c']);
    fireEvent.click(screen.getByRole('button', { name: 'Нет высоты — 1' }));
    expect(p.onSelectGroup).toHaveBeenCalledWith('status:height_missing', ['h']);
    expect(screen.getByText('Проёмы без данных — 2')).toBeInTheDocument();
    expect(screen.getByText('Двери без стены — 3')).toBeInTheDocument();
  });

  it('групп нет: об этом сказано, нулевая таблица не рисуется', () => {
    render(<ConstructionsPanel {...props({ data: constructionsRead() })} />);
    expect(screen.queryByRole('table')).toBeNull();
    expect(screen.getByText(/Посчитанных конструкций нет/)).toBeInTheDocument();
  });

  it('«Пересчитать» запускает расчёт и блокируется, пока он идёт', () => {
    const p = props();
    const { rerender } = render(<ConstructionsPanel {...p} />);
    fireEvent.click(screen.getByRole('button', { name: 'Пересчитать' }));
    expect(p.onCompute).toHaveBeenCalledTimes(1);
    rerender(<ConstructionsPanel {...props({ calculating: true })} />);
    expect(screen.getByRole('button', { name: 'Пересчитать' })).toBeDisabled();
    expect(screen.getByText('Пересчёт идёт…')).toBeInTheDocument();
    expect(screen.getByTestId('constructions-panel')).toBeInTheDocument();
  });

  it('свежий пересчёт упал: заметный отказ с причиной, старые данные и «Пересчитать» остались', () => {
    const p = props({ recomputeFailure: 'скрипт упал' });
    render(<ConstructionsPanel {...p} />);
    expect(screen.getByTestId('constructions-recompute-failed')).toHaveTextContent(
      'Пересчёт не удался: скрипт упал',
    );
    expect(screen.getByTestId('constructions-panel')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Пересчитать' }));
    expect(p.onCompute).toHaveBeenCalledTimes(1);
  });

  it('пересчёт идёт снова: отказ прежнего не показывается', () => {
    render(<ConstructionsPanel {...props({ calculating: true, recomputeFailure: 'скрипт упал' })} />);
    expect(screen.queryByTestId('constructions-recompute-failed')).toBeNull();
  });
});

describe('ConstructionsPanel: высоты листа', () => {
  it('значения с источниками, правка уходит в PUT /levels; пустое поле - null', () => {
    const p = props();
    render(<ConstructionsPanel {...p} />);
    expect(screen.getByText(/Высота этажа, мм/)).toBeInTheDocument();
    expect(screen.getAllByText(/Действует: 3\s000 мм \(выведено\)/).length).toBe(1);
    expect(screen.getByText(/Действует: 2\s100 мм \(допущение\)/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Высота этажа, мм', { selector: 'input' }), {
      target: { value: '3200' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить высоты' }));
    expect(p.onSaveLevels).toHaveBeenCalledWith({
      floor_height_mm: 3200,
      slab_thickness_mm: null,
      door_height_mm: null,
    });
  });

  it('значение вне диапазона не отправляется', () => {
    const p = props();
    render(<ConstructionsPanel {...p} />);
    fireEvent.change(screen.getByLabelText('Высота этажа, мм', { selector: 'input' }), {
      target: { value: '10' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить высоты' }));
    expect(screen.getByRole('alert')).toHaveTextContent('от 2000 до 6000');
    expect(p.onSaveLevels).not.toHaveBeenCalled();
  });

  it('нет высоты этажа: заметное «Нужна высота этажа», «не определено» - не 0', () => {
    const empty = constructionsRead({
      heights: {
        ...DATA.heights,
        floor_height: { default_mm: null, source: null, value_mm: null },
        wall_height_mm: null,
        wall_height_source: null,
      },
    });
    render(<ConstructionsPanel {...props({ data: empty })} />);
    expect(screen.getByRole('alert')).toHaveTextContent('Нужна высота этажа');
    expect(screen.getByText(/Высота стены:/)).toHaveTextContent('не определено');
    expect(screen.getByText(/Действует: не определено/)).toBeInTheDocument();
  });
});

describe('ConstructionsPanel: ВОР Заказчика', () => {
  it('без vor блока нет; с vor он идёт под сводом', () => {
    const { rerender } = render(<ConstructionsPanel {...props()} />);
    expect(screen.queryByRole('region', { name: 'ВОР Заказчика' })).toBeNull();
    const vor = {
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
    };
    rerender(<ConstructionsPanel {...props({ vor })} />);
    const totals = screen.getByRole('region', { name: 'Свод конструкций' });
    const block = screen.getByRole('region', { name: 'ВОР Заказчика' });
    expect(totals.compareDocumentPosition(block) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});

