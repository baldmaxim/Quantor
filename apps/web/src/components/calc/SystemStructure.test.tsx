import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { systemGraph } from './__fixtures__/synthesis';

import { SystemStructure } from './SystemStructure';

/**
 * Структура: дерево по связям, происхождение каждого элемента, диапазон как диапазон и блок
 * «Что Quantor пока не знает».
 */

describe('структура системы', () => {
  it('показывает связи, происхождение и кратность без выбора', () => {
    render(<SystemStructure graph={systemGraph()} onExplain={() => undefined} />);
    expect(screen.getByText('Ввод')).toBeInTheDocument();
    expect(screen.getAllByText('наблюдено')).toHaveLength(2);
    expect(screen.getByText('рассчитано')).toBeInTheDocument();
    expect(screen.getByText('4–5')).toBeInTheDocument();
    expect(screen.getByText(/Магистраль от ввода к стоякам · синтезировано/)).toBeInTheDocument();
    expect(screen.getByText('1 · ×24')).toBeInTheDocument();
    expect(screen.getByText('Элементы без установленных связей')).toBeInTheDocument();
  });

  it('перечисляет, что Quantor пока не знает', () => {
    render(<SystemStructure graph={systemGraph()} onExplain={() => undefined} />);
    expect(screen.getByText('Количество стояков')).toBeInTheDocument();
    expect(screen.getByText(/Известно: 4–5 по расчёту/)).toBeInTheDocument();
  });

  it('кнопка «Почему?» спрашивает объяснение элемента', () => {
    const onExplain = vi.fn();
    render(<SystemStructure graph={systemGraph()} onExplain={onExplain} />);
    const [, risers] = screen.getAllByRole('button', { name: 'Почему?' });
    if (!risers) throw new Error('нет кнопки у стояков');
    fireEvent.click(risers);
    expect(onExplain).toHaveBeenCalledWith('risers');
  });
});
