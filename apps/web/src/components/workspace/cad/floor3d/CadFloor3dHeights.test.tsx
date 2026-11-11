import { act, fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

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
  it('запись несёт все четыре поля: введённое и null у остальных', () => {
    const props = mount({}, { editing: true });
    fireEvent.change(field('Высота двери, мм'), { target: { value: '2200' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить высоты листа' }));
    expect(props.onSaveSheet).toHaveBeenCalledWith({
      floor_elevation_mm: null,
      floor_height_mm: null,
      slab_thickness_mm: null,
      door_height_mm: 2200,
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
