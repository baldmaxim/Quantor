import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';

import { CadTabs } from './CadTabs';

const TABS = [
  { id: 'a', label: 'Листы' },
  { id: 'b', label: 'Задания' },
] as const;

const Harness = () => {
  const [active, setActive] = useState<'a' | 'b'>('a');
  return (
    <CadTabs idPrefix="t" label="Раздел" tabs={TABS} active={active} onChange={setActive}>
      {active === 'a' ? <p>панель листов</p> : <p>панель заданий</p>}
    </CadTabs>
  );
};

describe('CadTabs', () => {
  it('рендерит только активную панель и связывает вкладку с панелью', () => {
    render(<Harness />);
    const tab = screen.getByRole('tab', { name: 'Листы' });
    expect(tab).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tabpanel')).toHaveAttribute('aria-labelledby', tab.id);
    expect(tab).toHaveAttribute('aria-controls', screen.getByRole('tabpanel').id);
    expect(screen.queryByText('панель заданий')).toBeNull();
  });

  it('клик и стрелка переключают вкладку', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('tab', { name: 'Задания' }));
    expect(screen.getByText('панель заданий')).toBeInTheDocument();
    expect(screen.queryByText('панель листов')).toBeNull();
    fireEvent.keyDown(screen.getByRole('tab', { name: 'Задания' }), { key: 'ArrowLeft' });
    expect(screen.getByText('панель листов')).toBeInTheDocument();
  });
});
