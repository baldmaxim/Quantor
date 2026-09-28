import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { passportSummary, volumeRows } from '../__fixtures__/vk';

import { VkOverview } from './VkOverview';
import { VkVolumes } from './VkVolumes';

/**
 * Объёмы паспорта ВК: диапазон — диапазоном, неизвестное — «не определено», частичный итог —
 * подтверждаемой частью, тендерный резерв — отдельно от базы.
 */

describe('объёмы паспорта ВК', () => {
  it('диапазон без середины и «не определено» вместо нуля', () => {
    render(<VkVolumes rows={volumeRows()} isError={false} onRetry={() => undefined} />);
    expect(screen.getByText('146,4–219,6 м')).toBeInTheDocument();
    expect(screen.queryByText(/183/)).not.toBeInTheDocument();
    expect(screen.getByText('не определено', { selector: 'span.font-mono' })).toBeInTheDocument();
    expect(screen.getByText(/подтверждено\s*236,4–458,1 м/)).toBeInTheDocument();
    expect(screen.getByText('топология графа')).toBeInTheDocument();
  });

  it('раскрытая позиция показывает составляющие и резерв отдельно', () => {
    render(<VkVolumes rows={volumeRows()} isError={false} onRetry={() => undefined} />);
    fireEvent.click(screen.getByRole('button', { name: /Трубы стояков/ }));
    expect(screen.getByText('— Межэтажная часть на стояк')).toBeInTheDocument();
    expect(screen.getByText(/База:/)).toBeInTheDocument();
    expect(screen.getByText('+2–3 м')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Почему это количество такое' })).toBeInTheDocument();
  });

  it('обзор показывает статус, рассчитанное и проблемы', () => {
    render(
      <VkOverview passports={[passportSummary()]} readiness={undefined} onOpen={() => undefined} />,
    );
    expect(screen.getByText('частично')).toBeInTheDocument();
    expect(screen.getByText('Трубы магистрали: не определено')).toBeInTheDocument();
    expect(screen.getByText('Правил, ожидающих инженера: 11')).toBeInTheDocument();
  });
});
