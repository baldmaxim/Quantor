import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { construction, constructionsRead } from '@/lib/cad/constructions-fixtures';
import { floor3dFixture } from '@/lib/cad/floor3d-fixtures';

import { CadFloor3dPopover } from './CadFloor3dPopover';

const mount = (key: string) => {
  const onDecide = vi.fn();
  render(
    <CadFloor3dPopover
      pick={{ kind: 'hole', category: 'hole', id: key }}
      model={floor3dFixture()}
      anchor={{ x: 10, y: 10 }}
      bounds={{ width: 600, height: 400 }}
      saving={false}
      error={null}
      onDecide={onDecide}
      onClose={vi.fn()}
    />,
  );
  return onDecide;
};

describe('плашка отверстия: кнопки по состоянию', () => {
  it('кандидат - обе кнопки', () => {
    const onDecide = mount('h1');
    fireEvent.click(screen.getByRole('button', { name: 'Отверстие' }));
    fireEvent.click(screen.getByRole('button', { name: 'Не отверстие' }));
    expect(onDecide.mock.calls).toEqual([
      ['h1', true],
      ['h1', false],
    ]);
  });

  it('включено - только «Не отверстие»', () => {
    mount('h2');
    expect(screen.queryByRole('button', { name: 'Отверстие' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Не отверстие' })).toBeInTheDocument();
  });

  it('не отверстие - состояние и только «Отверстие»', () => {
    const onDecide = mount('h3');
    expect(screen.getByRole('dialog', { name: 'Отверстие плиты' })).toHaveTextContent('не отверстие');
    expect(screen.queryByRole('button', { name: 'Не отверстие' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Отверстие' }));
    expect(onDecide).toHaveBeenCalledWith('h3', true);
  });
});

describe('плашка стены: величины из конструкций листа', () => {
  const mountWall = (data: ReturnType<typeof constructionsRead> | null) =>
    render(
      <CadFloor3dPopover
        pick={{ kind: 'prism', category: 'masonry', id: 'w1' }}
        model={floor3dFixture()}
        constructions={data}
        anchor={{ x: 10, y: 10 }}
        bounds={{ width: 600, height: 400 }}
        saving={false}
        error={null}
        onDecide={vi.fn()}
        onClose={vi.fn()}
      />,
    );

  it('длина, высота, площадь, объём, номинал и состояние', () => {
    mountWall(
      constructionsRead({
        constructions: [
          construction({
            id: 'w1',
            accepted: true,
            computed: { ...construction({ id: 'x' }).computed, length_m: 10, height_mm: 2800, wall_area_m2: 28, volume_m3: 5.6 },
          }),
        ],
      }),
    );
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveTextContent('Длина по оси: 10 м');
    expect(dialog).toHaveTextContent('Высота в расчёте: 2 800 мм');
    expect(dialog).toHaveTextContent('Площадь стены: 28 м²');
    expect(dialog).toHaveTextContent('Объём: 5,6 м³');
    expect(dialog).toHaveTextContent('Толщина (номинал): 200 мм');
    expect(dialog).toHaveTextContent('Состояние: принято');
  });

  it('не принято - «проверить»', () => {
    mountWall(constructionsRead({ constructions: [construction({ id: 'w1', accepted: false })] }));
    expect(screen.getByRole('dialog')).toHaveTextContent('Состояние: проверить');
  });

  it('нет данных конструкций - «Объём не определён», не 0', () => {
    mountWall(null);
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveTextContent('Объём не определён');
    expect(dialog).not.toHaveTextContent('0 м³');
    expect(dialog).not.toHaveTextContent('Состояние:');
  });

  it('конструкция есть, объёма нет - «Объём не определён»', () => {
    mountWall(
      constructionsRead({
        constructions: [
          construction({ id: 'w1', computed: { ...construction({ id: 'x' }).computed, volume_m3: null } }),
        ],
      }),
    );
    expect(screen.getByRole('dialog')).toHaveTextContent('Объём не определён');
  });
});

describe('плашка двери', () => {
  const mountDoor = (model = floor3dFixture(), id = 'o2') =>
    render(
      <CadFloor3dPopover
        pick={{ kind: 'prism', category: 'door', id }}
        model={model}
        anchor={{ x: 10, y: 10 }}
        bounds={{ width: 600, height: 400 }}
        saving={false}
        error={null}
        onDecide={vi.fn()}
        onClose={vi.fn()}
      />,
    );

  it('высота, источник, низ и верх в метрах', () => {
    mountDoor();
    const dialog = screen.getByRole('dialog', { name: 'Дверь' });
    expect(dialog).toHaveTextContent('Высота двери: 2000 мм (');
    expect(dialog).toHaveTextContent('Низ, м: 3,00');
    expect(dialog).toHaveTextContent('Верх, м: 5,00');
  });

  it('нет поля doors - плашки нет, ошибки нет', () => {
    mountDoor(floor3dFixture({ doors: undefined }));
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});

describe('плашка перемычки: материал', () => {
  const mountLintel = (patch: { material?: 'monolith' | 'masonry' | 'frame_partition' | null; kind?: 'door' | 'gap' }) => {
    const base = floor3dFixture();
    const lintel = { ...base.lintels[0]!, ...patch };
    render(
      <CadFloor3dPopover
        pick={{ kind: 'prism', category: 'lintel', id: 'o1' }}
        model={floor3dFixture({ lintels: [lintel] })}
        anchor={{ x: 10, y: 10 }}
        bounds={{ width: 600, height: 400 }}
        saving={false}
        error={null}
        onDecide={vi.fn()}
        onClose={vi.fn()}
      />,
    );
  };

  it('монолит над дверью и над проёмом', () => {
    mountLintel({ material: 'monolith' });
    expect(screen.getByRole('dialog', { name: 'Монолит над дверью' })).toHaveTextContent('Материал: монолит');
  });

  it('монолит над проёмом', () => {
    mountLintel({ material: 'monolith', kind: 'gap' });
    expect(screen.getByRole('dialog', { name: 'Монолит над проёмом' })).toBeInTheDocument();
  });

  it.each([
    ['masonry', 'кладка'],
    ['frame_partition', 'каркасная перегородка'],
  ] as const)('%s - заголовок прежний, материал в строке', (material, text) => {
    mountLintel({ material });
    expect(screen.getByRole('dialog', { name: 'Перемычка над дверью' })).toHaveTextContent(`Материал: ${text}`);
  });

  it('материала нет - «не определён»', () => {
    mountLintel({ material: null });
    expect(screen.getByRole('dialog', { name: 'Перемычка над дверью' })).toHaveTextContent('Материал: не определён');
  });
});
