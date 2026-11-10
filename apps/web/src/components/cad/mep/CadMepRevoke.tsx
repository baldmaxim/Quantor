'use client';

import type { CadDecisionRead } from '@quantor/api-client';
import { useState, type FC } from 'react';

import { Button, Dialog, DialogActions } from '@/components/ui';
import { ClearableInput } from '@/components/ui/ClearableInput';
import { mepErrorText } from '@/lib/cad/mep-gates';
import { useRevokeCadDecision } from '@/lib/cad/mep-queries';
import type { ICadViewParams } from '@/lib/cad/view-queries';

interface ICadMepRevokeProps {
  /** Вид, на котором стоит решение: обновляются его списки. */
  params: ICadViewParams;
  decision: CadDecisionRead;
  /** Подпись кнопки: «Отозвать одобрение» / «Отозвать принятие». */
  label: string;
  /** Что произойдёт после отзыва: показывается в окне подтверждения. */
  consequence: string;
  /** Отзыв сейчас невозможен: причина показана под кнопкой. */
  blockedReason?: string | null;
}

/**
 * Отзыв решения человека с подтверждением и необязательной причиной. Запись решения остаётся
 * (с отметкой отзыва), после отзыва вид или трассы можно одобрить и принять заново.
 */
export const CadMepRevoke: FC<ICadMepRevokeProps> = ({
  params,
  decision,
  label,
  consequence,
  blockedReason = null,
}) => {
  const revoke = useRevokeCadDecision(params);
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState('');
  const [problem, setProblem] = useState<string | null>(null);

  const close = () => {
    if (revoke.isPending) return;
    setOpen(false);
  };

  return (
    <div className="flex min-w-0 flex-col items-start gap-[var(--s-2)]">
      <Button
        onClick={() => {
          setProblem(null);
          setOpen(true);
        }}
        disabled={blockedReason !== null}
        className="max-md:h-[44px] max-md:w-full"
      >
        {label}
      </Button>
      {blockedReason && (
        <p className="text-xs text-muted" role="note">
          {blockedReason}
        </p>
      )}
      <Dialog
        open={open}
        onClose={close}
        busy={revoke.isPending}
        title={`${label}?`}
        description={consequence}
        onExited={() => {
          setReason('');
          setProblem(null);
          revoke.reset();
        }}
        footer={
          <DialogActions>
            <Button onClick={close} disabled={revoke.isPending}>
              Отмена
            </Button>
            <Button
              variant="primary"
              loading={revoke.isPending}
              loadingLabel="Отзываем…"
              onClick={() => {
                setProblem(null);
                revoke.mutate(
                  { decisionId: decision.id, reason },
                  {
                    onSuccess: () => setOpen(false),
                    onError: (error) => setProblem(mepErrorText(error)),
                  },
                );
              }}
            >
              Отозвать
            </Button>
          </DialogActions>
        }
      >
        <div className="flex min-w-0 flex-col gap-[var(--s-3)]">
          <label className="flex min-w-0 flex-col gap-[var(--s-2)] text-sm">
            <span>Причина (необязательно)</span>
            <ClearableInput
              label="Причина отзыва"
              autoComplete="off"
              maxLength={2000}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              onClear={() => setReason('')}
            />
          </label>
          {problem && (
            <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">
              {problem}
            </p>
          )}
        </div>
      </Dialog>
    </div>
  );
};
