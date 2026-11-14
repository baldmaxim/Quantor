'use client';

import { useState, type FC } from 'react';

import { Button } from '@/components/ui';
import { useBuildEom } from '@/lib/cad/eom-queries';
import { elevationError, floorHeightError, mepErrorText, optionalMm } from '@/lib/cad/mep-gates';
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
 * Шаг 2: «Построить трассы, ЭОМ и СС». По умолчанию отметку пола и высоту этажа генератор определяет
 * сам по документации (с источником и цитатой в итогах); «Задать вручную» - переопределение человека.
 * Одна кнопка ставит оба задания по одному одобренному виду и с одними значениями: сначала трассы
 * механики, затем ЭОМ и СС (`cad_eom_route`). Сервер идемпотентен: повторное нажатие с теми же
 * параметрами возвращает прежние задания, а не плодит новые.
 */
export const CadMepBuild: FC<ICadMepBuildProps> = ({
  parent,
  onCreated,
  hasRoutes = false,
  knownRouteJobIds = [],
  sections = null,
}) => {
  const build = useBuildMepRoutes(parent);
  const eom = useBuildEom(parent);
  const [eomProblem, setEomProblem] = useState<string | null>(null);
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
    if (!valid || build.isPending || eom.isPending) return;
    setProblem(null);
    setEomProblem(null);
    setWarnings([]);
    setReusedNotice(null);
    const known = new Set(knownRouteJobIds);
    const levels = {
      floorElevationMm: manual ? optionalMm(elevation) : null,
      floorHeightMm: manual ? optionalMm(height) : null,
    };
    build.mutate(levels, {
      onSuccess: (job) => {
        setWarnings(job.warnings ?? []);
        setReusedNotice(reusedRouteNotice(job, known));
        onCreated(job.job_id);
        // ЭОМ и СС - следом, по тому же виду и с теми же отметкой и высотой.
        eom.mutate(levels, { onError: (error) => setEomProblem(mepErrorText(error)) });
      },
      onError: (error) => setProblem(mepErrorText(error)),
    });
  };

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-4)]">
      <form
        aria-label="Построить трассы, ЭОМ и СС"
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
        <p className="text-xs text-muted">
          Вместе с трассами механики строятся ЭОМ и СС этажа: все системы — в общей спецификации
          (раздел 4), слои — в 3D этажа.
        </p>
        <Button
          type="submit"
          variant="primary"
          loading={build.isPending || eom.isPending}
          className="self-start max-md:h-[44px] max-md:w-full"
        >
          Построить трассы, ЭОМ и СС
        </Button>
        {problem && (
          <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">
            {problem}
          </p>
        )}
        {eomProblem && (
          <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">
            ЭОМ и СС не поставлены: {eomProblem}
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
