import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeAll, describe, expect, it, vi } from 'vitest';

import { DrawingScaleBadge } from './DrawingScaleBadge';
import { SheetTabs, type ISheetTab } from './SheetTabs';

const tab = (position: number, floorTitle = ''): ISheetTab => ({
  position,
  floorTitle,
  fullTitle: null,
  sheetLabel: `Лист ${position}`,
});

beforeAll(() => {
  // jsdom не реализует scrollIntoView.
  Element.prototype.scrollIntoView = vi.fn();
});

describe('SheetTabs', () => {
  it('одну вкладку закрыть нельзя', () => {
    render(<SheetTabs tabs={[tab(1)]} active={1} onActivate={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByRole('tab', { name: /Лист 1/ })).toHaveAttribute('aria-selected', 'true');
    expect(screen.queryByRole('button', { name: /Закрыть вкладку/ })).not.toBeInTheDocument();
  });

  it('щелчок активирует, крестик и средняя кнопка закрывают', async () => {
    const onActivate = vi.fn();
    const onClose = vi.fn();
    render(
      <SheetTabs
        tabs={[tab(1, 'К9 · С3 · 15 эт.'), tab(4), tab(7)]}
        active={1}
        onActivate={onActivate}
        onClose={onClose}
      />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole('tab', { name: /Лист 4/ }));
    expect(onActivate).toHaveBeenCalledWith(4);

    await user.click(screen.getByRole('button', { name: 'Закрыть вкладку: Лист 7' }));
    expect(onClose).toHaveBeenLastCalledWith(7);

    await user.pointer({ keys: '[MouseMiddle]', target: screen.getByRole('tab', { name: /15 эт/ }) });
    expect(onClose).toHaveBeenLastCalledWith(1);
  });
});

describe('DrawingScaleBadge', () => {
  it('масштаб, источник и масштаб вида', () => {
    render(<DrawingScaleBadge scale={{ text: '1:200', source: 'калибровка CAD', zoomPercent: 94 }} />);
    const badge = screen.getByTestId('drawing-scale');
    expect(badge).toHaveTextContent('Масштаб1:200калибровка CAD');
    expect(badge).toHaveTextContent('вид 94 %');
  });

  it('без масштаба - «не задан», а не число', () => {
    render(<DrawingScaleBadge scale={{ text: null, source: null, zoomPercent: 100 }} />);
    expect(screen.getByTestId('drawing-scale')).toHaveTextContent('Масштабне задан');
  });
});
