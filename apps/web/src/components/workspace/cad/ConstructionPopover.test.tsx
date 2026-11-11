import type { CadConstructionMaterialRead } from '@quantor/api-client';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { construction } from '@/lib/cad/constructions-fixtures';

import { ConstructionPopover } from './ConstructionPopover';
import type { IWorkspaceCadConstructionPopover } from './types';

const mount = (patch: Partial<IWorkspaceCadConstructionPopover> = {}) => {
  const handlers = {
    onClose: vi.fn(),
    onSave: vi.fn(),
    onBulk: vi.fn(),
    onAccept: vi.fn(),
  };
  render(
    <ConstructionPopover
      construction={construction({ id: 'a' })}
      doors={2}
      groupCount={3}
      anchor={{ x: 100, y: 100 }}
      saving={false}
      error={null}
      {...handlers}
      {...patch}
    />,
  );
  return handlers;
};

const dialog = () => screen.getByRole('dialog');

describe('ConstructionPopover: содержимое', () => {
  it('заголовок - вид и толщина; бейдж «Принято»', () => {
    mount({ construction: construction({ id: 'a', accepted: true }) });
    expect(dialog()).toHaveAccessibleName('Конструкция: Кладка, 120 мм');
    expect(screen.getByRole('heading', { name: 'Кладка, 120 мм' })).toBeInTheDocument();
    expect(screen.getByText('Принято')).toBeInTheDocument();
  });

  it('расчёт: величины с единицами, источник высоты, двери', () => {
    mount();
    expect(screen.getByText('5 м')).toBeInTheDocument();
    expect(screen.getByText('13,5 м²')).toBeInTheDocument();
    expect(screen.getByText('1,62 м³')).toBeInTheDocument();
    expect(screen.getByText(/2\s700 мм/)).toBeInTheDocument();
    expect(screen.getByText('(выведено)')).toBeInTheDocument();
    expect(screen.getByText('Двери в стене').nextSibling).toHaveTextContent('2');
  });

  it('нет высоты и толщины: «не определено» текстом, не 0; предупреждения по-русски', () => {
    const base = construction({ id: 'x' });
    mount({
      construction: construction({
        id: 'b',
        thickness_nominal_mm: null,
        computed: {
          ...base.computed,
          status: 'height_missing',
          height_mm: null,
          wall_area_m2: null,
          volume_m3: null,
          thickness_mm: null,
          warnings: ['height_missing', 'opening_no_data'],
        },
      }),
    });
    expect(screen.getByRole('heading', { name: 'Кладка, толщина не определена — проверить' })).toBeInTheDocument();
    expect(screen.getAllByText('не определено')).toHaveLength(3);
    expect(screen.getByText(/119,6 мм \/ не определено/)).toBeInTheDocument();
    expect(screen.queryByText(/^0 /)).toBeNull();
    expect(screen.getByText('Нет высоты')).toBeInTheDocument();
    expect(screen.getByText(/Высота не определена/)).toBeInTheDocument();
    expect(screen.getByText(/У проёма нет данных/)).toBeInTheDocument();
  });

  it('монолит: класс бетона и материал по умолчанию, полей кладки нет', () => {
    mount({ construction: construction({ id: 'm', kind: 'monolith_wall' }) });
    expect(screen.getByLabelText('Класс бетона')).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Монолитный железобетон (по умолчанию)' })).toBeInTheDocument();
    expect(screen.queryByLabelText('Раствор или клей')).toBeNull();
    expect(screen.queryByRole('group', { name: /Размер блока/ })).toBeNull();
  });

  it('поля блока и кирпича показываются по материалу', () => {
    mount();
    fireEvent.change(screen.getByLabelText('Материал'), { target: { value: 'brick_solid' } });
    expect(screen.getByLabelText('Кладка в кирпичах')).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: /Размер блока/ })).toBeNull();
    fireEvent.change(screen.getByLabelText('Материал'), { target: { value: 'aerated_concrete' } });
    expect(screen.getByRole('group', { name: /Размер блока/ })).toBeInTheDocument();
    expect(screen.queryByLabelText('Кладка в кирпичах')).toBeNull();
  });
});

describe('ConstructionPopover: материал и каркасная перегородка', () => {
  const documentMaterial: CadConstructionMaterialRead = {
    value: 'aerated_concrete',
    source: 'document',
    hint_status: 'matched',
    evidence: [{ text: 'Стены из газобетонных блоков 100 мм', page_index: 3, bbox: [0, 0, 1, 1] }],
  };

  it('материал из документа: бейдж с подсказкой, в поле формы пусто и плейсхолдер', () => {
    mount({ construction: construction({ id: 'a', material: documentMaterial }) });
    const badge = screen.getByText('из документа');
    expect(badge.closest('span[title]')).toHaveAttribute(
      'title',
      'Стены из газобетонных блоков 100 мм',
    );
    const select = screen.getByLabelText('Материал', { selector: 'select' });
    expect(select).toHaveValue('');
    expect(screen.getByRole('option', { name: 'По документу: Газобетон' })).toBeInTheDocument();
  });

  it('material_check: бейдж «проверить материал»', () => {
    const base = construction({ id: 'x' });
    mount({
      construction: construction({
        id: 'a',
        material: { value: null, source: null, hint_status: 'conflict', evidence: [] },
        computed: { ...base.computed, warnings: ['material_check'] },
      }),
    });
    expect(screen.getByText('проверить материал')).toBeInTheDocument();
    expect(screen.getByText(/Проверить материал: в условных обозначениях/)).toBeInTheDocument();
  });

  it('каркасная перегородка ГКЛ: вид, площадь, объём «—», полей кладки нет', () => {
    const base = construction({ id: 'x' });
    mount({
      construction: construction({
        id: 'p',
        kind: 'frame_partition',
        computed: { ...base.computed, volume_m3: null },
      }),
    });
    expect(screen.getByRole('heading', { name: 'Каркасная перегородка ГКЛ, 120 мм' })).toBeInTheDocument();
    expect(screen.getByText('13,5 м²')).toBeInTheDocument();
    expect(screen.getByText('Объём').nextSibling).toHaveTextContent('—');
    expect(screen.queryByLabelText('Раствор или клей')).not.toBeInTheDocument();
  });
});

describe('ConstructionPopover: закрытие', () => {
  it('Esc, крестик и щелчок вне закрывают; щелчок внутри - нет', () => {
    const { onClose } = mount();
    fireEvent.pointerDown(dialog());
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Закрыть карточку' }));
    expect(onClose).toHaveBeenCalledTimes(2);
    fireEvent.pointerDown(document.body);
    expect(onClose).toHaveBeenCalledTimes(3);
  });
});

describe('ConstructionPopover: положение', () => {
  afterEach(() => vi.restoreAllMocks());

  it('у правого края окна переворачивается влево от точки клика', () => {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
      width: 340,
      height: 400,
    } as DOMRect);
    mount({ anchor: { x: window.innerWidth - 20, y: 50 } });
    expect(dialog().style.left).toBe(`${window.innerWidth - 20 - 12 - 340}px`);
    expect(dialog().style.top).toBe('62px');
  });

  it('карточка прокручивается внутри и не растягивает окно', () => {
    mount();
    expect(dialog().className).toContain('max-h-[70dvh]');
    expect(dialog().className).toContain('overscroll-contain');
  });
});

describe('ConstructionPopover: форма', () => {
  it('«Сохранить» отдаёт заполненные поля', () => {
    const { onSave } = mount();
    fireEvent.change(screen.getByLabelText('Материал'), { target: { value: 'aerated_concrete' } });
    fireEvent.change(screen.getByLabelText('Шов, мм', { selector: 'input' }), { target: { value: '3' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(onSave).toHaveBeenCalledWith({
      material: 'aerated_concrete',
      joint_mm: 3,
      count_openings: true,
    });
  });

  it('ошибка ввода блокирует сохранение и объяснена текстом', () => {
    const { onSave } = mount();
    fireEvent.change(screen.getByLabelText('Шов, мм', { selector: 'input' }), { target: { value: '99' } });
    expect(screen.getByRole('alert')).toHaveTextContent('Шов, мм: целое число от 1 до 30.');
    expect(screen.getByRole('button', { name: 'Сохранить' })).toBeDisabled();
    expect(onSave).not.toHaveBeenCalled();
  });

  it('«Применить ко всем» - подпись с видом, толщиной и числом; шлёт только заполненные поля', () => {
    const { onBulk } = mount();
    const bulk = screen.getByRole('button', { name: 'Применить ко всем: Кладка 120 мм на листе (3 шт.)' });
    expect(bulk).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Назначение'), { target: { value: 'interior' } });
    expect(bulk).toBeEnabled();
    fireEvent.click(bulk);
    expect(onBulk).toHaveBeenCalledWith({ purpose: 'interior' });
  });

  it('крестик очищает поле и оставляет в нём фокус', () => {
    mount();
    const note = screen.getByLabelText('Примечание', { selector: 'input' });
    fireEvent.change(note, { target: { value: 'текст' } });
    fireEvent.click(screen.getByRole('button', { name: 'Очистить: Примечание' }));
    expect(note).toHaveValue('');
    expect(note).toHaveFocus();
  });

  it('«Принять» / «Снять принятие»: недоступно, пока есть несохранённые изменения', () => {
    const { onAccept } = mount();
    fireEvent.click(screen.getByRole('button', { name: 'Принять' }));
    expect(onAccept).toHaveBeenCalledWith(true);
    fireEvent.change(screen.getByLabelText('Назначение'), { target: { value: 'mop' } });
    expect(screen.getByRole('button', { name: 'Принять' })).toBeDisabled();
  });

  it('принятая конструкция: кнопка снимает принятие', () => {
    const { onAccept } = mount({ construction: construction({ id: 'a', accepted: true }) });
    fireEvent.click(screen.getByRole('button', { name: 'Снять принятие' }));
    expect(onAccept).toHaveBeenCalledWith(false);
  });

  it('отказ сервера показан в карточке', () => {
    mount({ error: 'Данные запроса не приняты.' });
    expect(screen.getByText('Данные запроса не приняты.')).toBeInTheDocument();
  });
});

describe('ConstructionPopover: плита перекрытия', () => {
  const base = construction({ id: 'x' });
  const slab = (patch: Partial<ReturnType<typeof construction>> = {}) =>
    construction({
      id: 'slab',
      kind: 'floor_slab',
      thickness_nominal_mm: 200,
      computed: {
        ...base.computed,
        thickness_mm: 200,
        height_mm: null,
        length_m: null,
        wall_area_m2: null,
        area_m2: 52.5,
        volume_m3: 10.5,
      },
      ...patch,
    });

  it('заголовок «Плита перекрытия»; площадь нетто, толщина, объём; без длины, высоты и стены', () => {
    mount({ construction: slab(), groupCount: 1 });
    expect(dialog()).toHaveAccessibleName('Конструкция: Плита перекрытия');
    expect(screen.getByRole('heading', { name: 'Плита перекрытия' })).toBeInTheDocument();
    expect(screen.getByText('Площадь (нетто)').nextSibling).toHaveTextContent('52,5 м²');
    expect(screen.getByText('Толщина').nextSibling).toHaveTextContent('200 мм');
    expect(screen.getByText('Объём').nextSibling).toHaveTextContent('10,5 м³');
    for (const label of ['Длина', 'Высота', 'Площадь стены', 'Двери в стене']) {
      expect(screen.queryByText(label)).toBeNull();
    }
  });

  it('форма плиты: материал и ручная толщина; высоты, проёмов, кладки и «применить ко всем» нет', () => {
    mount({ construction: slab(), groupCount: 1 });
    expect(screen.getByLabelText('Материал')).toBeInTheDocument();
    expect(screen.getByLabelText('Толщина вручную, мм', { exact: false })).toBeInTheDocument();
    expect(screen.queryByLabelText('Высота вручную, мм', { exact: false })).toBeNull();
    expect(screen.queryByLabelText('Учитывать надпроёмные части')).toBeNull();
    expect(screen.queryByLabelText('Раствор или клей')).toBeNull();
    expect(screen.queryByLabelText('Назначение')).toBeNull();
    expect(screen.queryByRole('button', { name: /Применить ко всем/ })).toBeNull();
    expect(screen.getByRole('button', { name: 'Сохранить' })).toBeInTheDocument();
  });

  it('толщина не задана: бейдж «Толщина плиты не задана», «не определено» вместо нуля', () => {
    mount({
      construction: slab({
        thickness_nominal_mm: null,
        computed: {
          ...base.computed,
          status: 'thickness_check',
          thickness_mm: null,
          height_mm: null,
          length_m: null,
          wall_area_m2: null,
          area_m2: 52.5,
          volume_m3: null,
          warnings: ['thickness_check'],
        },
      }),
      groupCount: 1,
    });
    expect(screen.getAllByText('Толщина плиты не задана').length).toBeGreaterThan(0);
    expect(screen.getByText('Толщина').nextSibling).toHaveTextContent('не определено');
    expect(screen.getByText('Объём').nextSibling).toHaveTextContent('не определено');
  });
});

