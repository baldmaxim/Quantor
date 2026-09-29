import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { factType } from './__fixtures__/calc';

import { ManualFactDialog, type IManualTarget } from './ManualFactDialog';

/**
 * Ручной ввод — последний путь: без основания значение не записывается, допущение возможно
 * только там, где его разрешает политика требования, и всегда с альтернативами.
 */

const mutate = vi.fn();

vi.mock('@/lib/calc/fact-actions', () => ({
  useAddManualFact: () => ({ mutate, isPending: false, isError: false, error: null }),
}));

const TARGET: IManualTarget = {
  type: factType(),
  title: 'Квартиры на этажах — В1',
  discipline: 'VK',
  systemCode: 'В1',
};

const fill = async (label: string, text: string) => {
  await userEvent.type(screen.getByLabelText(label), text);
};

describe('ручной ввод значения', () => {
  beforeEach(() => mutate.mockReset());

  it('без основания значение не записывается', async () => {
    render(<ManualFactDialog projectId="p-1" target={TARGET} onClose={vi.fn()} />);
    await fill('Этаж или группа этажей', '3');
    await fill('Значение, кв.', '9');
    await userEvent.click(screen.getByRole('button', { name: 'Записать' }));
    expect(screen.getByText('Укажите основание: документ, лист или решение')).toBeInTheDocument();
    expect(mutate).not.toHaveBeenCalled();
  });

  it('записывает место, значение и основание', async () => {
    render(<ManualFactDialog projectId="p-1" target={TARGET} onClose={vi.fn()} />);
    await fill('Этаж или группа этажей', '3');
    await fill('Значение, кв.', '9');
    await fill('Основание', 'план 3 этажа, лист АР-5');
    await userEvent.click(screen.getByRole('button', { name: 'Записать' }));
    expect(mutate).toHaveBeenCalledTimes(1);
    expect(mutate.mock.calls[0]?.[0]).toEqual({
      factType: 'floor.apartments_count',
      subject: { building: '1', floor: '3' },
      value: { kind: 'COUNT', value: 9 },
      note: 'план 3 этажа, лист АР-5',
      alternatives: undefined,
    });
  });

  it('допущение не предлагается, если политика требования его запрещает', () => {
    render(<ManualFactDialog projectId="p-1" target={TARGET} onClose={vi.fn()} />);
    expect(screen.queryByLabelText(/Это допущение/)).toBeNull();
  });

  it('допущение требует альтернатив', async () => {
    render(
      <ManualFactDialog
        projectId="p-1"
        target={{ ...TARGET, assumptionAllowed: true }}
        onClose={vi.fn()}
      />,
    );
    await fill('Этаж или группа этажей', '3');
    await fill('Значение, кв.', '9');
    await fill('Основание', 'типовой этаж по аналогу');
    await userEvent.click(screen.getByLabelText(/Это допущение/));
    await userEvent.click(screen.getByRole('button', { name: 'Записать' }));
    expect(mutate).not.toHaveBeenCalled();
    await fill('Альтернативы — через «;»', '8; 10');
    await userEvent.click(screen.getByRole('button', { name: 'Записать' }));
    expect(mutate.mock.calls[0]?.[0]).toMatchObject({ alternatives: ['8', '10'] });
  });
});
