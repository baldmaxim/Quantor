import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { CadWindowLevelsApplyRead } from '@quantor/api-client';

import { heightsFixture } from '@/lib/cad/floor3d-fixtures';

import { CadFloor3dHeights } from './CadFloor3dHeights';

const edit = () => fireEvent.click(screen.getByRole('button', { name: 'Редактировать' }));

const mount = (
  patch: Partial<Parameters<typeof CadFloor3dHeights>[0]> = {},
  { editing = false }: { editing?: boolean } = {},
) => {
  const props = {
    heights: heightsFixture(),
    elevationKnown: true,
    projectLevels: { slab_thickness_mm: null, slab_source_ref: null, updated_at: null },
    sheetSaving: false,
    projectSaving: false,
    error: null,
    onSaveSheet: vi.fn(),
    onSaveProject: vi.fn(),
    ...patch,
  };
  const view = render(<CadFloor3dHeights {...props} />);
  if (editing) edit();
  return { ...props, view };
};

const field = (name: string) => screen.getByRole('textbox', { name });

describe('панель высот: источники', () => {
  it('значение и источник по-русски у каждой высоты', () => {
    mount();
    expect(screen.getByTestId('floor3d-value-floor_elevation_mm')).toHaveTextContent(
      '3000 мм (чертёж)',
    );
    expect(screen.getByTestId('floor3d-value-floor_height_mm')).toHaveTextContent(
      '3000 мм (выведено)',
    );
    expect(screen.getByTestId('floor3d-value-slab_thickness_mm')).toHaveTextContent(
      '200 мм (допущение)',
    );
    expect(screen.getByTestId('floor3d-value-door_height_mm')).toHaveTextContent(
      '2100 мм (допущение)',
    );
  });

  it('ввод человека и «не определено»', () => {
    mount({
      heights: heightsFixture({
        floor_elevation_mm: null,
        floor_elevation_source: null,
        door_height: { value_mm: 2300, source: 'manual', default_mm: 2100 },
      }),
      elevationKnown: false,
    });
    expect(screen.getByTestId('floor3d-value-floor_elevation_mm')).toHaveTextContent(
      'не определено',
    );
    expect(screen.getByTestId('floor3d-value-door_height_mm')).toHaveTextContent('2300 мм (ввод)');
    expect(screen.getByRole('note')).toHaveTextContent(
      'Отметка не определена — этаж построен от 0.',
    );
  });

  it('отметка известна - плашки нет', () => {
    mount();
    expect(screen.queryByRole('note')).toBeNull();
  });
});

describe('панель высот: просмотр и редактирование', () => {
  it('по умолчанию - просмотр без полей ввода, есть «Редактировать»', () => {
    mount();
    expect(screen.queryByRole('textbox')).toBeNull();
    expect(screen.queryByRole('button', { name: /Сохранить/ })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Отмена' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Редактировать' })).toBeInTheDocument();
  });

  it('«Редактировать» открывает формы с «Сохранить» и «Отмена»', () => {
    mount();
    edit();
    expect(field('Высота двери, мм')).toBeInTheDocument();
    expect(field('Толщина плиты по разрезу, мм')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Сохранить высоты листа' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Отмена' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Редактировать' })).toBeNull();
  });

  it('«Отмена» возвращает просмотр; изменения не сохраняются', () => {
    const props = mount();
    edit();
    fireEvent.change(field('Высота двери, мм'), { target: { value: '2200' } });
    fireEvent.click(screen.getByRole('button', { name: 'Отмена' }));
    expect(screen.queryByRole('textbox')).toBeNull();
    expect(props.onSaveSheet).not.toHaveBeenCalled();
    edit();
    expect(field('Высота двери, мм')).toHaveValue('');
  });

  it('успешное сохранение возвращает просмотр, отказ оставляет форму', () => {
    const { view, ...props } = mount({}, { editing: true });
    const next = (patch: Partial<Parameters<typeof CadFloor3dHeights>[0]>) =>
      view.rerender(<CadFloor3dHeights {...props} {...patch} />);
    next({ sheetSaving: true });
    expect(field('Высота двери, мм')).toBeInTheDocument();
    act(() => next({ sheetSaving: false, error: 'Сервер отказал.' }));
    expect(field('Высота двери, мм')).toBeInTheDocument();

    next({ sheetSaving: true, error: null });
    act(() => next({ sheetSaving: false, error: null }));
    expect(screen.queryByRole('textbox')).toBeNull();
    expect(screen.getByRole('button', { name: 'Редактировать' })).toBeInTheDocument();
  });

  it('просмотр толщины плиты проекта: значение и лист разреза', () => {
    mount({
      projectLevels: { slab_thickness_mm: 220, slab_source_ref: 'АР л. 45', updated_at: null },
    });
    expect(screen.getByTestId('floor3d-value-project-slab')).toHaveTextContent(
      '220 мм (разрез: АР л. 45)',
    );
  });

  it('«Отметка не определена» видна и в просмотре, и в редактировании', () => {
    mount({ elevationKnown: false });
    expect(screen.getByRole('note')).toBeInTheDocument();
    edit();
    expect(screen.getByRole('note')).toBeInTheDocument();
  });
});

describe('панель высот: переопределения листа', () => {
  it('запись несёт все шесть полей: введённое и null у остальных', () => {
    const props = mount({}, { editing: true });
    fireEvent.change(field('Высота двери, мм'), { target: { value: '2200' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить высоты листа' }));
    expect(props.onSaveSheet).toHaveBeenCalledWith({
      floor_elevation_mm: null,
      floor_height_mm: null,
      slab_thickness_mm: null,
      door_height_mm: 2200,
      window_sill_mm: null,
      window_head_mm: null,
    });
  });

  it('текущее переопределение подставлено в поле, пустое поле снимает его (null)', () => {
    const props = mount(
      {
        heights: heightsFixture({
          door_height: { value_mm: 2300, source: 'manual', default_mm: 2100 },
        }),
      },
      { editing: true },
    );
    expect(field('Высота двери, мм')).toHaveValue('2300');
    fireEvent.click(screen.getByRole('button', { name: 'Очистить: Высота двери, мм' }));
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить высоты листа' }));
    expect(props.onSaveSheet).toHaveBeenCalledWith(
      expect.objectContaining({ door_height_mm: null }),
    );
  });

  it('толщина плиты из разреза проекта не подставляется как переопределение листа', () => {
    mount(
      {
        heights: heightsFixture({
          slab_thickness: { value_mm: 220, source: 'manual', default_mm: 200 },
          slab_thickness_sheet_ref: 'АР л. 45',
        }),
      },
      { editing: true },
    );
    expect(field('Толщина плиты листа, мм')).toHaveValue('');
    expect(screen.getByText(/взята из разреза проекта: АР л\. 45/)).toBeInTheDocument();
  });

  it('значение вне диапазона не отправляется', () => {
    const props = mount({}, { editing: true });
    fireEvent.change(field('Высота этажа, мм'), { target: { value: '10' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить высоты листа' }));
    expect(props.onSaveSheet).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent('Высота этажа, мм');
  });
});

describe('панель высот: толщина плиты проекта', () => {
  it('число без листа разреза не отправляется', () => {
    const props = mount({}, { editing: true });
    fireEvent.change(field('Толщина плиты по разрезу, мм'), { target: { value: '220' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить толщину проекта' }));
    expect(props.onSaveProject).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent('лист разреза');
  });

  it('число и лист разреза уходят вместе', () => {
    const props = mount({}, { editing: true });
    fireEvent.change(field('Толщина плиты по разрезу, мм'), { target: { value: '220' } });
    fireEvent.change(field('Лист разреза'), { target: { value: 'АР1.1 л. 45, разрез 4-4' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить толщину проекта' }));
    expect(props.onSaveProject).toHaveBeenCalledWith({
      slab_thickness_mm: 220,
      slab_source_ref: 'АР1.1 л. 45, разрез 4-4',
    });
  });

  it('пустое число снимает значение проекта', () => {
    const props = mount(
      {
        projectLevels: { slab_thickness_mm: 220, slab_source_ref: 'АР л. 45', updated_at: null },
      },
      { editing: true },
    );
    fireEvent.click(screen.getByRole('button', { name: 'Очистить: Толщина плиты по разрезу, мм' }));
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить толщину проекта' }));
    expect(props.onSaveProject).toHaveBeenCalledWith({
      slab_thickness_mm: null,
      slab_source_ref: null,
    });
  });
});

const WINDOWS_SAVED = {
  window_sill: { value_mm: 900, source: 'manual', default_mm: null },
  window_head: { value_mm: 2400, source: 'manual', default_mm: null },
} as const;

const applyResult = (patch: Partial<CadWindowLevelsApplyRead> = {}): CadWindowLevelsApplyRead => ({
  sill_mm: 900,
  head_mm: 2400,
  dry_run: true,
  group_label: 'Корп. 1 · сек. 3',
  updated: 4,
  skipped: [{ label: 'Лист 9', reason: 'other_group' }],
  ...patch,
});

describe('панель высот: подоконник и высота окна листа', () => {
  it('не заданы - «не определено», не 0; ввод - «ввод»', () => {
    mount();
    expect(screen.getByTestId('floor3d-value-window_sill_mm')).toHaveTextContent('не определено');
    expect(screen.getByTestId('floor3d-value-window_head_mm')).toHaveTextContent('не определено');
  });

  it('сохранённая пара показана с источником и подставлена в поля', () => {
    mount({ heights: heightsFixture(WINDOWS_SAVED) }, { editing: true });
    expect(screen.getByTestId('floor3d-value-window_sill_mm')).toHaveTextContent('900 мм (ввод)');
    expect(field('Подоконник, мм')).toHaveValue('900');
    expect(field('Высота окна (верх от чистого пола), мм')).toHaveValue('2400');
  });

  it('пара уходит в запись вместе с остальными полями', () => {
    const props = mount({}, { editing: true });
    fireEvent.change(field('Подоконник, мм'), { target: { value: '900' } });
    fireEvent.change(field('Высота окна (верх от чистого пола), мм'), { target: { value: '2400' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить высоты листа' }));
    expect(props.onSaveSheet).toHaveBeenCalledWith({
      floor_elevation_mm: null,
      floor_height_mm: null,
      slab_thickness_mm: null,
      door_height_mm: null,
      window_sill_mm: 900,
      window_head_mm: 2400,
    });
  });

  it.each([
    ['только подоконник', '900', '', 'вместе'],
    ['только высота окна', '', '2400', 'вместе'],
    ['подоконник не ниже верха', '2400', '2400', 'ниже верха'],
    ['верх выше 6000', '0', '6001', 'от 1 до 6000'],
    ['отрицательный подоконник', '-5', '1000', 'от 0 до 5999'],
  ])('%s - не отправляется', (_name, sill, head, text) => {
    const props = mount({}, { editing: true });
    fireEvent.change(field('Подоконник, мм'), { target: { value: sill } });
    fireEvent.change(field('Высота окна (верх от чистого пола), мм'), { target: { value: head } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить высоты листа' }));
    expect(props.onSaveSheet).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent(text);
  });

  it('пустая пара снимает ручной ввод (null)', () => {
    const props = mount({ heights: heightsFixture(WINDOWS_SAVED) }, { editing: true });
    fireEvent.click(screen.getByRole('button', { name: 'Очистить: Подоконник, мм' }));
    fireEvent.click(
      screen.getByRole('button', { name: 'Очистить: Высота окна (верх от чистого пола), мм' }),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить высоты листа' }));
    expect(props.onSaveSheet).toHaveBeenCalledWith(
      expect.objectContaining({ window_sill_mm: null, window_head_mm: null }),
    );
  });
});

describe('панель высот: применить ко всей секции', () => {
  const section = (patch: Partial<Parameters<typeof CadFloor3dHeights>[0]> = {}) => ({
    heights: heightsFixture(WINDOWS_SAVED),
    sectionLabel: 'корп. 1, сек. 3',
    onPreviewSection: vi.fn().mockResolvedValue(applyResult()),
    onApplySection: vi.fn().mockResolvedValue(applyResult({ dry_run: false })),
    ...patch,
  });
  const button = () => screen.getByRole('button', { name: 'Применить ко всей секции' });

  it('без обработчиков блока секции нет', () => {
    mount({}, { editing: true });
    expect(screen.queryByRole('button', { name: 'Применить ко всей секции' })).toBeNull();
  });

  it('нет корпуса или секции - кнопка недоступна с подсказкой', () => {
    mount(section({ sectionLabel: null }), { editing: true });
    expect(button()).toBeDisabled();
    expect(screen.getByTestId('floor3d-window-section')).toHaveTextContent(
      'нет корпуса или секции',
    );
  });

  it('значения листа не сохранены - кнопка недоступна', () => {
    mount(section({ heights: heightsFixture() }), { editing: true });
    expect(button()).toBeDisabled();
    expect(screen.getByTestId('floor3d-window-section')).toHaveTextContent('Сначала сохраните');
  });

  it('подтверждение несёт число листов из ответа; применение - по кнопке', async () => {
    const props = mount(section(), { editing: true });
    expect(button()).toBeEnabled();
    fireEvent.click(button());
    const confirm = await screen.findByRole('group', { name: 'Подтверждение' });
    expect(props.onPreviewSection).toHaveBeenCalledTimes(1);
    expect(props.onApplySection).not.toHaveBeenCalled();
    expect(confirm).toHaveTextContent('Подоконник 900 мм и высота окна 2400 мм');
    expect(confirm).toHaveTextContent('Листов: 4');
    expect(confirm).toHaveTextContent('Пропущено листов: 1');
    fireEvent.click(screen.getByRole('button', { name: 'Применить к листам: 4' }));
    await waitFor(() => expect(props.onApplySection).toHaveBeenCalledTimes(1));
    expect(await screen.findByRole('status')).toHaveTextContent('Применено: листов секции - 4');
    expect(screen.queryByRole('group', { name: 'Подтверждение' })).toBeNull();
  });

  it('«Отмена» подтверждения ничего не записывает', async () => {
    const props = mount(section(), { editing: true });
    fireEvent.click(button());
    await screen.findByRole('group', { name: 'Подтверждение' });
    fireEvent.click(within(screen.getByRole('group', { name: 'Подтверждение' })).getByRole('button', { name: 'Отмена' }));
    expect(screen.queryByRole('group', { name: 'Подтверждение' })).toBeNull();
    expect(props.onApplySection).not.toHaveBeenCalled();
  });

  it('отказ сервера показан, подтверждения нет', async () => {
    mount(section({ onPreviewSection: vi.fn().mockRejectedValue(new Error('boom')) }), {
      editing: true,
    });
    fireEvent.click(button());
    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Подтверждение' })).toBeNull();
  });
});
