'use client';

import { useState, type FC } from 'react';

import { Button } from '@/components/ui';
import {
  elevationError,
  floorHeightError,
  mepErrorText,
  optionalMm,
} from '@/lib/cad/mep-gates';
import { reusedRouteNotice } from '@/lib/cad/mep-reuse';
import { useBuildMepRoutes } from '@/lib/cad/mep-queries';
import { sectionWarningText } from '@/lib/cad/sections';
import type { ICadViewParams } from '@/lib/cad/view-queries';

import type { IWorkspaceCadSectionsLink } from '@/components/workspace/cad/types';

import { CadMepFloorFields } from './CadMepFloorFields';
import { CadMepSectionsLink } from './CadMepSectionsLink';

interface ICadMepBuildProps {
  parent: ICadViewParams;
  /** Задание поставлено (или найдено прежнее по этому одобрению): открыть его. */
  onCreated: (routeJobId: string) => void;
  /** По действующему одобрению трассы уже строились: правят их пересчётом. */
  hasRoutes?: boolean;
  /** Id заданий трасс вида, известных панели до нажатия: по ним узнаём прежнее задание. */
  knownRouteJobIds?: readonly string[];
  /** Разрезы ревизии: блок «Высота из разрезов»; `null` - блока нет. */
  sections?: IWorkspaceCadSectionsLink | null;
}

/**
 * Шаг 2: «Построить трассы». По умолчанию отметку пола и высоту этажа генератор определяет сам
 * по документации (с источником и цитатой в итогах); «Задать вручную» - переопределение человека.
 */
export const CadMepBuild: FC<ICadMepBuildProps> = ({
  parent,
  onCreated,
  hasRoutes = false,
  knownRouteJobIds = [],
  sections = null,
}) => {
  const build = useBuildMepRoutes(parent);
  const [manual, setManual] = useState(false);
  const [elevation, setElevation] = useState('');
  const [height, setHeight] = useState('');
  const [touched, setTouched] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  // Предупреждения постановки (например, неоднозначная высота по разрезам); в задании тоже хранятся.
  const [warnings, setWarnings] = useState<readonly string[]>([]);
  // Сервер идемпотентен: при тех же параметрах вернул прежнее задание - скажем об этом.
  const [reusedNotice, setReusedNotice] = useState<string | null>(null);

  const elevationProblem = manual ? elevationError(elevation) : null;
  const heightProblem = manual ? floorHeightError(height) : null;
  const valid = elevationProblem === null && heightProblem === null;

  const submit = () => {
    setTouched(true);
    if (!valid || build.isPending) return;
    setProblem(null);
    setWarnings([]);
    setReusedNotice(null);
    const known = new Set(knownRouteJobIds);
    build.mutate(
      {
        floorElevationMm: manual ? optionalMm(elevation) : null,
        floorHeightMm: manual ? optionalMm(height) : null,
      },
      {
        onSuccess: (job) => {
          setWarnings(job.warnings ?? []);
          setReusedNotice(reusedRouteNotice(job, known));
          onCreated(job.job_id);
        },
        onError: (error) => setProblem(mepErrorText(error)),
      },
    );
  };

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-4)]">
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
        {reusedNotice && (
          <p role="status" className="text-xs text-muted [overflow-wrap:anywhere]">
            {reusedNotice}
          </p>
        )}
        {warnings.map((code) => (
          <p key={code} role="note" className="text-xs text-warning [overflow-wrap:anywhere]">
            {sectionWarningText(code)}
          </p>
        ))}
      </form>
      {sections && <CadMepSectionsLink {...sections} />}
    </div>
  );
};
