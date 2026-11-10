'use client';

import type { CadJobRead } from '@quantor/api-client';
import { useState, type FC } from 'react';

import { Button, Dialog, DialogActions } from '@/components/ui';
import {
  elevationError,
  floorHeightError,
  initialFloorText,
  mepErrorText,
  needsManualFloor,
  optionalMm,
  recomputeBlock,
} from '@/lib/cad/mep-gates';
import { floorSourceLabel } from '@/lib/cad/mep-candidate';
import { useRecomputeMepRoutes } from '@/lib/cad/mep-queries';
import type { ICadViewParams } from '@/lib/cad/view-queries';

import { CadMepFloorFields } from './CadMepFloorFields';

interface ICadMepRecomputeProps {
  /** Route-задание (проект, ревизия, задание): пересчёт - новая попытка этого же задания. */
  target: ICadViewParams;
  job: CadJobRead;
  /** Трассы этого задания приняты: пересчёт закрыт до отзыва принятия. */
  accepted: boolean;
}

const requestedOf = (job: CadJobRead): { elevation: number | null; height: number | null } => {
  const last = job.route_attempts?.[job.route_attempts.length - 1];
  if (last) return { elevation: last.requested_elevation_mm, height: last.requested_height_mm };
  return {
    elevation: job.floor_elevation_source === 'operator' ? job.floor_elevation_mm : null,
    height: job.floor_height_source === 'operator' ? job.floor_height_mm : null,
  };
};

const valueText = (value: number | null, source: string | null): string =>
  value === null ? '—' : `${value} мм (${floorSourceLabel(source)})`;

/**
 * Пересчёт трасс: новая попытка того же задания с другими отметкой пола и высотой этажа
 * (пустое поле - по документации). Открытые замечания переходят в новую попытку, прошлые
 * попытки остаются в истории расчётов.
 */
export const CadMepRecompute: FC<ICadMepRecomputeProps> = ({ target, job, accepted }) => {
  const recompute = useRecomputeMepRoutes(target);
  const manualNeeded = job.status === 'failed' && needsManualFloor(job.error_code);
  const requested = requestedOf(job);
  const [open, setOpen] = useState(false);
  const [elevation, setElevation] = useState(String(requested.elevation ?? ''));
  const [height, setHeight] = useState(String(requested.height ?? ''));
  const [touched, setTouched] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const block = recomputeBlock({
    status: job.status,
    accepted,
    approvalRevoked: job.approval_revoked ?? false,
  });
  const shown = (open || manualNeeded) && block === null;

  const elevationProblem = elevationError(elevation);
  const heightProblem = floorHeightError(height);
  const valid = elevationProblem === null && heightProblem === null;
  const elevationValue = optionalMm(elevation);
  const heightValue = optionalMm(height);
  const unchanged = elevationValue === requested.elevation && heightValue === requested.height;

  const start = () => {
    setProblem(null);
    recompute.mutate(
      { floorElevationMm: elevationValue, floorHeightMm: heightValue },
      {
        onSuccess: () => {
          setConfirm(false);
          setOpen(false);
        },
        onError: (error) => {
          setConfirm(false);
          setProblem(mepErrorText(error));
        },
      },
    );
  };

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-3)]" data-testid="mep-recompute">
      <p className="text-xs text-muted [overflow-wrap:anywhere]">
        Отметка пола: {valueText(job.floor_elevation_mm, job.floor_elevation_source ?? null)}.
        Высота этажа: {valueText(job.floor_height_mm, job.floor_height_source ?? null)}.
      </p>
      {manualNeeded && block === null && (
        <p role="note" className="text-xs text-danger">
          Не найдено в документации: задайте отметку и высоту вручную.
        </p>
      )}
      {!shown && (
        <Button
          onClick={() => {
            setProblem(null);
            setTouched(false);
            setElevation(
              requested.elevation !== null
                ? String(requested.elevation)
                : initialFloorText(job.floor_elevation_mm, job.floor_elevation_source),
            );
            setHeight(requested.height !== null ? String(requested.height) : '');
            setOpen(true);
          }}
          disabled={block !== null}
          className="self-start max-md:h-[44px] max-md:w-full"
        >
          Пересчитать…
        </Button>
      )}
      {block && (
        <p className="text-xs text-muted" role="note">
          {block}
        </p>
      )}
      {shown && (
        <form
          aria-label="Пересчитать трассы"
          className="flex min-w-0 flex-col gap-[var(--s-4)]"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            setTouched(true);
            if (valid) setConfirm(true);
          }}
        >
          <CadMepFloorFields
            elevation={elevation}
            height={height}
            onElevation={setElevation}
            onHeight={setHeight}
            elevationProblem={elevationProblem}
            heightProblem={heightProblem}
            showProblems={touched}
          />
          {unchanged && valid && (
            <p className="text-xs text-muted" role="note">
              Те же значения, что в текущей попытке: пересчёт пройдёт, только если обновился
              генератор трасс.
            </p>
          )}
          <div className="flex min-w-0 flex-wrap gap-[var(--s-3)]">
            <Button
              type="submit"
              variant="primary"
              className="max-md:h-[44px] max-md:w-full"
            >
              Пересчитать
            </Button>
            {!manualNeeded && (
              <Button onClick={() => setOpen(false)} className="max-md:h-[44px] max-md:w-full">
                Отмена
              </Button>
            )}
          </div>
        </form>
      )}
      {problem && (
        <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">
          {problem}
        </p>
      )}
      <Dialog
        open={confirm}
        onClose={() => !recompute.isPending && setConfirm(false)}
        busy={recompute.isPending}
        title="Пересчитать трассы?"
        description={`Начнётся попытка ${job.attempt + 1} этого же задания. Открытые замечания перейдут в неё, прошлые попытки останутся в истории расчётов.`}
        onExited={() => recompute.reset()}
        footer={
          <DialogActions>
            <Button onClick={() => setConfirm(false)} disabled={recompute.isPending}>
              Отмена
            </Button>
            <Button
              variant="primary"
              loading={recompute.isPending}
              loadingLabel="Ставим…"
              onClick={start}
            >
              Пересчитать
            </Button>
          </DialogActions>
        }
      >
        <p className="text-sm [overflow-wrap:anywhere]">
          Отметка пола: {elevationValue === null ? 'по документации' : `${elevationValue} мм`}.
          Высота этажа: {heightValue === null ? 'по документации' : `${heightValue} мм`}.
        </p>
      </Dialog>
    </div>
  );
};
