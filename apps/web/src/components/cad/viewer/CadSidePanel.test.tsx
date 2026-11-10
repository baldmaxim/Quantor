import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { CadSidePanel, type ICadSideTab } from './CadSidePanel';

const TABS: readonly ICadSideTab[] = [
  { id: 'layers', label: 'Слои', content: <p>панель слоёв</p> },
  { id: 'remarks', label: 'Замечания', content: <input aria-label="Черновик" /> },
  { id: 'scale', label: 'Масштаб', content: <p>панель масштаба</p> },
  { id: 'files', label: 'Файлы', content: <p>панель файлов</p> },
  { id: 'job', label: 'Задание', content: <p>панель задания</p> },
];

describe('CadSidePanel', () => {
  it('пять разделов в заданном порядке, открыт первый', () => {
    render(<CadSidePanel label="Панель вида" tabs={TABS} />);
    expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
      'Слои',
      'Замечания',
      'Масштаб',
      'Файлы',
      'Задание',
    ]);
    expect(screen.getByRole('tab', { name: 'Слои' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tabpanel')).toHaveTextContent('панель слоёв');
  });

  it('клик и стрелки переключают раздел; видна только открытая панель', () => {
    render(<CadSidePanel label="Панель вида" tabs={TABS} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Масштаб' }));
    expect(screen.getByRole('tabpanel')).toHaveTextContent('панель масштаба');
    expect(screen.queryByText('панель слоёв')).not.toBeVisible();

    fireEvent.keyDown(screen.getByRole('tab', { name: 'Масштаб' }), { key: 'ArrowRight' });
    expect(screen.getByRole('tabpanel')).toHaveTextContent('панель файлов');
    fireEvent.keyDown(screen.getByRole('tab', { name: 'Файлы' }), { key: 'ArrowLeft' });
    expect(screen.getByRole('tabpanel')).toHaveTextContent('панель масштаба');
  });

  it('скрытые разделы остаются смонтированными: введённый текст не теряется', () => {
    render(<CadSidePanel label="Панель вида" tabs={TABS} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Замечания' }));
    fireEvent.change(screen.getByLabelText('Черновик'), { target: { value: 'текст' } });
    fireEvent.click(screen.getByRole('tab', { name: 'Файлы' }));
    fireEvent.click(screen.getByRole('tab', { name: 'Замечания' }));
    expect(screen.getByLabelText('Черновик')).toHaveValue('текст');
  });

  it('раздел можно задать снаружи и узнать о выборе', () => {
    const chosen: string[] = [];
    render(
      <CadSidePanel
        label="Панель вида"
        tabs={TABS}
       
        active="job"
        onActiveChange={(id) => chosen.push(id)}
      />,
    );
    expect(screen.getByRole('tabpanel')).toHaveTextContent('панель задания');
    fireEvent.click(screen.getByRole('tab', { name: 'Файлы' }));
    expect(chosen).toEqual(['files']);
  });

  it('собственных рамок и кнопки сворачивания нет: ими ведает каркас рабочей области', () => {
    render(<CadSidePanel label="Панель вида" tabs={TABS} />);
    expect(screen.getByRole('region', { name: 'Панель вида' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Свернуть/ })).toBeNull();
    expect(screen.queryByRole('complementary')).toBeNull();
  });

  it('раздела, которого нет в списке, не открывает: берётся первый', () => {
    render(<CadSidePanel label="Панель вида" tabs={TABS.slice(4)} active="layers" />);
    expect(screen.getByRole('tabpanel')).toHaveTextContent('панель задания');
  });
});
