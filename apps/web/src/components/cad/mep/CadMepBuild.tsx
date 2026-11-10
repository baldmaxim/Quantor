'use client';

import { useState, type FC } from 'react';

import { Button } from '@/components/ui';
import { ClearableInput } from '@/components/ui/ClearableInput';
import {
  elevationError,
  floorHeightError,
  mepErrorText,
  parseMm,
} from '@/lib/cad/mep-gates';
import { useBuildMepRoutes } from '@/lib/cad/mep-queries';
import type { ICadViewParams } from '@/lib/cad/view-queries';

interface ICadMepBuildProps {
  parent: ICadViewParams;
  /** Задание поставлено (или найдено прежнее с теми же параметрами): открыть его. */
  onCreated: (routeJobId: string) => void;
}

const LABEL = 'flex min-w-0 flex-col gap-[var(--s-2)] text-sm';

/**
 * Шаг 2: «Построить трассы». Отметка пола и высота этажа - ввод человека, обязательные, без
 * умолчаний: генератор не подставляет их сам.
 */
export const CadMepBuild: FC<ICadMepBuildProps> = ({ parent, onCreated }) => {
  const build = useBuildMepRoutes(parent);
  const [elevation, setElevation] = useState('');
  const [height, setHeight] = useState('');
  const [touched, setTouched] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const elevationProblem = elevationError(elevation);
  const heightProblem = floorHeightError(height);
  const valid = elevationProblem === null && heightProblem === null;

  const submit = () => {
    setTouched(true);
    const floorElevationMm = parseMm(elevation);
    const floorHeightMm = parseMm(height);
    if (!valid || floorElevationMm === null || floorHeightMm === null || build.isPending) return;
    setProblem(null);
    build.mutate(
      { floorElevationMm, floorHeightMm },
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
      <label className={LABEL}>
        <span>Отметка пола, мм</span>
        <ClearableInput
          label="Отметка пола, мм"
          inputMode="numeric"
          autoComplete="off"
          placeholder="например, 47600"
          value={elevation}
          onChange={(event) => setElevation(event.target.value)}
          onClear={() => setElevation('')}
          aria-invalid={touched && elevationProblem !== null}
        />
        {touched && elevationProblem && (
          <span role="alert" className="text-xs text-danger">
            {elevationProblem}
          </span>
        )}
      </label>
      <label className={LABEL}>
        <span>Высота этажа, мм</span>
        <ClearableInput
          label="Высота этажа, мм"
          inputMode="numeric"
          autoComplete="off"
          placeholder="например, 3300"
          value={height}
          onChange={(event) => setHeight(event.target.value)}
          onClear={() => setHeight('')}
          aria-invalid={touched && heightProblem !== null}
        />
        {touched && heightProblem && (
          <span role="alert" className="text-xs text-danger">
            {heightProblem}
          </span>
        )}
      </label>
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
