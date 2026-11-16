import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { CadTenderLayers, type ICadTenderLayerItem } from './CadTenderLayers';

const item = (patch: Partial<ICadTenderLayerItem> = {}): ICadTenderLayerItem => ({
  calcId: 'c1',
  title: 'Отопление · №3 v3',
  color: 'var(--tender-sys-heating)',
  visible: true,
  baseStale: false,
  ...patch,
});

describe('группа «Расчёты» панели «Слои»', () => {
  it('строка на версию расчёта с флажком', () => {
    render(<CadTenderLayers items={[item(), item({ calcId: 'c2', title: 'Вентиляция · №1 v1', visible: false })]} onSetVisible={vi.fn()} />);
    expect(screen.getByText('Расчёты')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /Отопление/ })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /Вентиляция/ })).not.toBeChecked();
  });

  it('флажок строки переключает именно этот расчёт', () => {
    const onSetVisible = vi.fn();
    render(<CadTenderLayers items={[item(), item({ calcId: 'c2', title: 'Вентиляция · №1 v1' })]} onSetVisible={onSetVisible} />);
    fireEvent.click(screen.getByRole('checkbox', { name: /Вентиляция/ }));
    expect(onSetVisible).toHaveBeenCalledWith(['c2'], false);
  });

  it('переключатель группы действует на все расчёты', () => {
    const onSetVisible = vi.fn();
    render(<CadTenderLayers items={[item(), item({ calcId: 'c2', title: 'Вентиляция · №1 v1' })]} onSetVisible={onSetVisible} />);
    fireEvent.click(screen.getByRole('checkbox', { name: 'Группа «Расчёты»' }));
    expect(onSetVisible).toHaveBeenCalledWith(['c1', 'c2'], false);
  });

  it('значок «база устарела» только у устаревшего расчёта', () => {
    render(<CadTenderLayers items={[item(), item({ calcId: 'c2', title: 'Вентиляция · №1 v1', baseStale: true })]} onSetVisible={vi.fn()} />);
    expect(screen.getAllByText('база устарела')).toHaveLength(1);
  });
});
