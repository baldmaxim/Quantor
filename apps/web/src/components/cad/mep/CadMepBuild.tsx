'use client';

import { useState, type FC } from 'react';

import { Button } from '@/components/ui';
import {
  elevationError,
  floorHeightError,
  mepErrorText,
  optionalMm,
} from '@/lib/cad/mep-gates';
import { useBuildMepRoutes } from '@/lib/cad/mep-queries';
import type { ICadViewParams } from '@/lib/cad/view-queries';

import { CadMepFloorFields } from './CadMepFloorFields';

interface ICadMepBuildProps {
  parent: ICadViewParams;
  /** Задание поставлено (или найдено прежнее по этому одобрению): открыть его. */
  onCreated: (routeJobId: string) => void;
  /** По действующему одобрению трассы уже строились: правят их пересчётом. */
  hasRoutes?: boolean;
}

/**
 * Шаг 2: «Построить трассы». По умолчанию отметку пола и высоту этажа генератор определяет сам
 * по документации (с источником и цитатой в итогах); «Задать вручную» - переопределение человека.
 */
export const CadMepBuild: FC<ICadMepBuildProps> = ({ parent, onCreated, hasRoutes = false }) => {
  const build = useBuildMepRoutes(parent);
  const [manual, setManual] = useState(false);
  const [elevation, setElevation] = useState('');
  const [height, setHeight] = useState('');
  const [touched, setTouched] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const elevationProblem = manual ? elevationError(elevation) : null;
  const heightProblem = manual ? floorHeightError(height) : null;
  const valid = elevationProblem === null && heightProblem === null;

  const submit = () => {
    setTouched(true);
    if (!valid || build.isPending) return;
    setProblem(null);
    build.mutate(
      {
        floorElevationMm: manual ? optionalMm(elevation) : null,
        floorHeightMm: manual ? optionalMm(height) : null,
      },
      {
        onSuccess: (job) => onCreated(job.job_id),
        onError: (error) => setProblem(mepErrorText(error)),
      },
    );
  };

  return (
    <form
      aria-label="Построить трассы"
      className="flex min-w-0 flex-col gap-[var(--s-4)]"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      {manual ? (
        <CadMepFloorFields
          elevation={elevation}
          height={height}
          onElevation={setElevation}
          onHeight={setHeight}
          elevationProblem={elevationProblem}
          heightProblem={heightProblem}
          showProblems={touched}
        />
      ) : (
        <p className="text-xs text-muted">
          Отметка и высота этажа будут определены по документации.
        </p>
      )}
      <Button
        onClick={() => {
          setManual((value) => !value);
          setTouched(false);
        }}
        className="self-start max-md:h-[44px] max-md:w-full"
        aria-expanded={manual}
      >
        {manual ? 'Определить по документации' : 'Задать вручную'}
      </Button>
      {hasRoutes && (
        <p className="text-xs text-muted" role="note">
          Для этого одобрения трассы уже построены: «Построить» откроет их, а менять отметку и
          высоту нужно кнопкой «Пересчитать» в разделе 3.
        </p>
      )}
      <Button
        type="submit"
        variant="primary"
        loading={build.isPending}
        className="self-start max-md:h-[44px] max-md:w-full"
      >
        Построить трассы
      </Button>
      {problem && (
        <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">
          {problem}
        </p>
      )}
    </form>
  );
};
