import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { need, ruleVersion } from './__fixtures__/rule-needs';

import { RuleDecisionDialog } from './RuleDecisionDialog';
import { RuleReviewDialog } from './RuleReviewDialog';

/**
 * Решения инженера: черновик собирается из того, что ввёл инженер; утверждает другой человек —
 * у автора кнопки «Утвердить» нет.
 */

const save = vi.fn();
const approve = vi.fn();
const reject = vi.fn();
const VERSION = ruleVersion();

const mutation = (mutate: typeof save) => ({
  mutate,
  isPending: false,
  isError: false,
  error: null,
});

vi.mock('@/lib/calc/rule-needs-queries', () => ({
  useCalcRuleDetail: (ruleKey: string | null) => ({
    data: ruleKey ? { rule_key: ruleKey, versions: [VERSION] } : undefined,
    isError: false,
    refetch: vi.fn(),
  }),
  useSaveRuleDecision: () => mutation(save),
  useApproveRule: () => mutation(approve),
  useRejectRule: () => mutation(reject),
}));

describe('решение инженера по заявке', () => {
  beforeEach(() => {
    save.mockReset();
    approve.mockReset();
    reject.mockReset();
  });

  it('черновик записывается со значениями и основанием инженера', async () => {
    render(
      <RuleDecisionDialog target={{ need: need(), state: { kind: 'none' } }} onClose={vi.fn()} />,
    );
    await userEvent.type(screen.getByLabelText(/нижняя граница/), '2');
    await userEvent.type(screen.getByLabelText(/верхняя граница/), '3');
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить черновик' }));
    expect(save).not.toHaveBeenCalled();
    expect(screen.getByText('Основание: заполните «Название методики»')).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText('Название методики'), 'Методика гейта');
    await userEvent.type(screen.getByLabelText('Автор или организация'), 'Инженер ВК');
    await userEvent.type(screen.getByLabelText('Где опубликована или хранится'), 'протокол');
    await userEvent.type(screen.getByLabelText('Суть методики и ограничения'), 'по схемам');
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить черновик' }));
    expect(save).toHaveBeenCalledTimes(1);
    const [payload] = save.mock.calls[0] ?? [];
    expect(payload.ruleKey).toBe('vk.b1.risers.count_range');
    expect(payload.body.parameters).toEqual([
      { name: 'per_riser_min', value: '2' },
      { name: 'per_riser_max', value: '3' },
    ]);
    expect(payload.body.change_reason).toBeNull();
  });

  it('после утверждения новая версия требует причины', async () => {
    render(
      <RuleDecisionDialog
        target={{ need: need(), state: { kind: 'approved', version: 1 } }}
        onClose={vi.fn()}
      />,
    );
    // Значения и основание — из прежней версии.
    expect(screen.getByLabelText(/нижняя граница/)).toHaveValue('2');
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить черновик' }));
    expect(save).not.toHaveBeenCalled();
    expect(screen.getByText('Укажите, почему нужна новая версия')).toBeInTheDocument();
  });
});

describe('проверка черновика правила', () => {
  it('автор не видит кнопки «Утвердить», но может отклонить', async () => {
    render(
      <RuleReviewDialog
        target={{ ruleKey: 'vk.b1.risers.count_range', version: 1 }}
        currentUserId="u-author"
        onClose={vi.fn()}
      />,
    );
    expect(screen.queryByRole('button', { name: 'Утвердить' })).toBeNull();
    expect(screen.getByText(/утверждает другой человек/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/Комментарий/), 'значения не по схеме');
    await userEvent.click(screen.getByRole('button', { name: 'Отклонить' }));
    expect(reject).toHaveBeenCalledWith(
      { ruleKey: 'vk.b1.risers.count_range', version: 1, comment: 'значения не по схеме' },
      expect.anything(),
    );
  });

  it('другой человек утверждает с комментарием', async () => {
    render(
      <RuleReviewDialog
        target={{ ruleKey: 'vk.b1.risers.count_range', version: 1 }}
        currentUserId="u-reviewer"
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByText('Методика «Методика», Инженер: протокол. суть')).toBeInTheDocument();
    const button = screen.getByRole('button', { name: 'Утвердить' });
    expect(button).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/Комментарий/), 'сверено со схемой В1');
    await userEvent.click(button);
    expect(approve).toHaveBeenCalledTimes(1);
  });
});
