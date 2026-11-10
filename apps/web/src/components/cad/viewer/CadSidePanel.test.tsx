import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { resetStoredFlags } from '@/lib/cad/useStoredFlag';

import { CadSidePanel, type ICadSideTab } from './CadSidePanel';

const KEY = 'test:side-collapsed';

const TABS: readonly ICadSideTab[] = [
  { id: 'layers', label: 'Слои', content: <p>панель слоёв</p> },
  { id: 'remarks', label: 'Замечания', content: <input aria-label="Черновик" /> },
  { id: 'scale', label: 'Масштаб', content: <p>панель масштаба</p> },
  { id: 'files', label: 'Файлы', content: <p>панель файлов</p> },
  { id: 'job', label: 'Задание', content: <p>панель задания</p> },
];

beforeEach(() => {
  window.localStorage.clear();
  resetStoredFlags();
});

describe('CadSidePanel', () => {
  it('пять разделов в заданном порядке, открыт первый', () => {
    render(<CadSidePanel label="Панель вида" tabs={TABS} storageKey={KEY} />);
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
    render(<CadSidePanel label="Панель вида" tabs={TABS} storageKey={KEY} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Масштаб' }));
    expect(screen.getByRole('tabpanel')).toHaveTextContent('панель масштаба');
    expect(screen.queryByText('панель слоёв')).not.toBeVisible();

    fireEvent.keyDown(screen.getByRole('tab', { name: 'Масштаб' }), { key: 'ArrowRight' });
    expect(screen.getByRole('tabpanel')).toHaveTextContent('панель файлов');
    fireEvent.keyDown(screen.getByRole('tab', { name: 'Файлы' }), { key: 'ArrowLeft' });
    expect(screen.getByRole('tabpanel')).toHaveTextContent('панель масштаба');
  });

  it('скрытые разделы остаются смонтированными: введённый текст не теряется', () => {
    render(<CadSidePanel label="Панель вида" tabs={TABS} storageKey={KEY} />);
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
        storageKey={KEY}
        active="job"
        onActiveChange={(id) => chosen.push(id)}
      />,
    );
    expect(screen.getByRole('tabpanel')).toHaveTextContent('панель задания');
    fireEvent.click(screen.getByRole('tab', { name: 'Файлы' }));
    expect(chosen).toEqual(['files']);
  });

  it('сворачивается кнопкой, состояние пишется в localStorage и возвращается кнопкой полосы', () => {
    render(<CadSidePanel label="Панель вида" tabs={TABS} storageKey={KEY} />);
    const aside = screen.getByRole('complementary', { name: 'Панель вида' });
    expect(aside).toHaveAttribute('data-collapsed', 'false');
    expect(screen.queryByTestId('cad-side-collapsed')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Свернуть боковую панель' }));
    expect(window.localStorage.getItem(KEY)).toBe('1');
    expect(screen.getByTestId('cad-side-collapsed')).toBeInTheDocument();
    expect(screen.getByTestId('cad-side-collapsed').className).toContain('lg:flex');
    expect(aside).toHaveAttribute('data-collapsed', 'true');
    expect(aside.className).toContain('lg:hidden');

    fireEvent.click(screen.getByRole('button', { name: 'Показать боковую панель' }));
    expect(window.localStorage.getItem(KEY)).toBe('0');
    expect(screen.queryByTestId('cad-side-collapsed')).toBeNull();
    expect(aside).toHaveAttribute('data-collapsed', 'false');
  });

  it('свёрнутость переживает перемонтирование', () => {
    window.localStorage.setItem(KEY, '1');
    render(<CadSidePanel label="Панель вида" tabs={TABS} storageKey={KEY} />);
    expect(screen.getByTestId('cad-side-collapsed')).toBeInTheDocument();
  });
});
