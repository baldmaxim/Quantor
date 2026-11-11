import type {
  CadPipelineSheetRead,
  CadPipelineStageRead,
  CadPipelineViewRead,
} from '@quantor/api-client';

import { floor3dDxfUrl } from './floor3d-dxf';
import {
  convertStep,
  PIPELINE_STEP_LABELS,
  sheetSteps,
  VIEW_KEYS,
  viewSteps,
  type IPipelineStep,
  type PipelineStepKey,
  type ViewStepKey,
} from './pipeline';
import { workspaceCadHref } from './workspace-url';

/**
 * Действия панели «Обработка» по шагам листа (без UI): что можно запустить или куда перейти.
 *
 * Калибровка, одобрение вида и принятие трасс - решения человека: для них только ссылка в рабочую
 * область, автоматически они не запускаются. Идущий шаг не отменяется (отмены на сервере нет).
 */

export type PipelineActionKind =
  /** Новое задание преобразования листа в CAD. */
  | 'convert'
  /** Повтор упавшего задания преобразования. */
  | 'retry'
  /** Пересчёт конструкций вида. */
  | 'walls'
  /** Автоматическая разметка зон. */
  | 'zones-auto'
  /** Сборка 3D DXF этажа. */
  | 'floor3d'
  /** Переход в рабочую область. */
  | 'link'
  /** Скачивание готового файла. */
  | 'download';

/** `fix` - чинит упавший шаг, `start` - запускает не начатый, `redo` - повторяет готовый, `open` - переход. */
export type PipelineActionIntent = 'fix' | 'start' | 'redo' | 'open';

export interface IPipelineAction {
  /** Уникален в пределах листа: шаг, вид и вид действия. */
  readonly id: string;
  readonly kind: PipelineActionKind;
  readonly intent: PipelineActionIntent;
  readonly label: string;
  /** Задание, над которым работает действие: родитель вида (`walls`, `zones-auto`, `floor3d`) или повторяемое. */
  readonly jobId: string | null;
  readonly pageIndex: number;
  readonly view: number | null;
  /** Адрес для `link` и `download`. */
  readonly href: string | null;
  /** Перед запуском нужно подтверждение. */
  readonly confirm: boolean;
}

export interface IPipelineRow {
  readonly id: string;
  readonly key: PipelineStepKey;
  /** Номер вида; `null` - шаг листа целиком (или вид один и подпись не нужна, см. `viewLabel`). */
  readonly view: number | null;
  /** Подпись вида «Вид N» - только когда у листа несколько видов с DXF. */
  readonly viewLabel: string | null;
  readonly step: IPipelineStep;
  /** Последнее задание шага: от него зависят подробности отказа. */
  readonly stage: CadPipelineStageRead | null;
  readonly actions: readonly IPipelineAction[];
}

export interface IPipelineNext {
  readonly row: IPipelineRow;
  readonly action: IPipelineAction;
}

/** Действие запускает работу на сервере (не переход и не скачивание). */
export const isMachineAction = (action: IPipelineAction): boolean =>
  action.kind !== 'link' && action.kind !== 'download';

interface IContext {
  readonly projectId: string;
  readonly revisionId: string;
  readonly position: number;
  readonly sheet: CadPipelineSheetRead;
}

const action = (
  base: Pick<IPipelineAction, 'id' | 'kind' | 'intent' | 'label'> & Partial<IPipelineAction>,
  context: IContext,
): IPipelineAction => ({
  jobId: null,
  pageIndex: context.sheet.page_index,
  view: null,
  href: null,
  confirm: false,
  ...base,
});

const linkTo = (
  context: IContext,
  id: string,
  label: string,
  view: number | null,
  withJob: boolean,
): IPipelineAction =>
  action(
    {
      id,
      kind: 'link',
      intent: 'open',
      label,
      view,
      href: workspaceCadHref(context.projectId, {
        revision: context.revisionId,
        position: context.position,
        job: withJob ? (context.sheet.convert?.job_id ?? null) : null,
        view: withJob ? view : null,
      }),
    },
    context,
  );

const calibrationActions = (step: IPipelineStep, context: IContext): IPipelineAction[] =>
  step.state === 'todo' ? [linkTo(context, 'calibration:link', 'Откалибровать', null, false)] : [];

const convertActions = (step: IPipelineStep, context: IContext): IPipelineAction[] => {
  const convert = context.sheet.convert;
  if (step.state === 'failed' && convert) {
    return [
      action(
        {
          id: 'convert:retry',
          kind: 'retry',
          intent: 'fix',
          label: 'Повторить',
          jobId: convert.job_id,
        },
        context,
      ),
    ];
  }
  if (step.state === 'done') {
    return [
      action(
        {
          id: 'convert:again',
          kind: 'convert',
          intent: 'redo',
          label: 'Преобразовать заново',
          confirm: true,
        },
        context,
      ),
    ];
  }
  if (step.state === 'todo') {
    return [
      action(
        { id: 'convert:start', kind: 'convert', intent: 'start', label: 'Запустить' },
        context,
      ),
    ];
  }
  return [];
};

const wallsActions = (
  step: IPipelineStep,
  view: CadPipelineViewRead,
  context: IContext,
): IPipelineAction[] => {
  const jobId = context.sheet.convert?.job_id ?? null;
  const id = `walls:${view.view}`;
  const base = { kind: 'walls', view: view.view, jobId } as const;
  if (step.state === 'failed') {
    return [action({ ...base, id, intent: 'fix', label: 'Пересчитать' }, context)];
  }
  if (step.state === 'done') {
    return [action({ ...base, id, intent: 'redo', label: 'Пересчитать' }, context)];
  }
  if (step.state === 'todo') {
    return [action({ ...base, id, intent: 'start', label: 'Запустить' }, context)];
  }
  return [];
};

const zonesActions = (
  step: IPipelineStep,
  view: CadPipelineViewRead,
  context: IContext,
): IPipelineAction[] => {
  if (step.state === 'running') return [];
  // Автоматическая разметка по уже размеченному листу отвечает 409: там только переход к зонам.
  if (view.zones_count > 0) {
    return [linkTo(context, `zones:${view.view}:link`, 'Открыть зоны', view.view, true)];
  }
  const intent = step.state === 'failed' ? 'fix' : step.state === 'todo' ? 'start' : 'redo';
  return [
    action(
      {
        id: `zones:${view.view}`,
        kind: 'zones-auto',
        intent,
        label: 'Разметить автоматически',
        view: view.view,
        jobId: context.sheet.convert?.job_id ?? null,
      },
      context,
    ),
  ];
};

const approvalActions = (
  step: IPipelineStep,
  view: CadPipelineViewRead,
  context: IContext,
): IPipelineAction[] =>
  step.state === 'review'
    ? [linkTo(context, `approval:${view.view}:link`, 'Проверить вид', view.view, true)]
    : [];

/**
 * Трассы: «Пересчитать» (`/recompute`) не подходит как повтор - сервер требует действующее
 * одобрение и другие отметку или высоту, иначе 409 `CAD_RECOMPUTE_SAME_PARAMS`. Поэтому и для
 * упавших, и для ждущих построения или принятия - переход в рабочую область. Упавшее задание
 * трасс повторяется как есть (`/retry` принимает задания трасс).
 */
const routesActions = (
  step: IPipelineStep,
  view: CadPipelineViewRead,
  context: IContext,
): IPipelineAction[] => {
  const link = linkTo(context, `routes:${view.view}:link`, 'Открыть трассы', view.view, true);
  if (step.state === 'failed' && view.routes) {
    const retry = action(
      {
        id: `routes:${view.view}:retry`,
        kind: 'retry',
        intent: 'fix',
        label: 'Повторить',
        view: view.view,
        jobId: view.routes.job_id,
      },
      context,
    );
    return [retry, link];
  }
  return step.state === 'todo' || step.state === 'review' ? [link] : [];
};

const floor3dActions = (
  step: IPipelineStep,
  view: CadPipelineViewRead,
  context: IContext,
): IPipelineAction[] => {
  const jobId = context.sheet.convert?.job_id ?? null;
  const base = { kind: 'floor3d', view: view.view, jobId } as const;
  const id = `floor3d:${view.view}`;
  if (step.state === 'todo') {
    return [action({ ...base, id, intent: 'start', label: 'Собрать 3D DXF' }, context)];
  }
  if (step.state === 'failed') {
    return [action({ ...base, id, intent: 'fix', label: 'Повторить' }, context)];
  }
  if (step.state === 'done') {
    const result: IPipelineAction[] = [
      action({ ...base, id, intent: 'redo', label: 'Собрать заново' }, context),
    ];
    if (view.floor3d) {
      result.push(
        action(
          {
            id: `${id}:download`,
            kind: 'download',
            intent: 'open',
            label: 'Скачать',
            view: view.view,
            href: floor3dDxfUrl(
              context.projectId,
              context.revisionId,
              view.floor3d.job_id,
              view.page,
              view.view,
            ),
          },
          context,
        ),
      );
    }
    return result;
  }
  return [];
};

const stageOf = (key: ViewStepKey, view: CadPipelineViewRead): CadPipelineStageRead | null => {
  if (key === 'walls') return view.walls;
  if (key === 'zones') return view.zones;
  if (key === 'routes') return view.routes;
  if (key === 'floor3d') return view.floor3d;
  return null;
};

const viewActions = (
  key: ViewStepKey,
  step: IPipelineStep,
  view: CadPipelineViewRead,
  context: IContext,
): IPipelineAction[] => {
  switch (key) {
    case 'walls':
      return wallsActions(step, view, context);
    case 'zones':
      return zonesActions(step, view, context);
    case 'approval':
      return approvalActions(step, view, context);
    case 'routes':
      return routesActions(step, view, context);
    case 'floor3d':
      return floor3dActions(step, view, context);
  }
};

/**
 * 3D DXF собирается по конструкциям этажа и от принятия трасс не зависит; общий вывод шагов
 * показывает его «ждёт предыдущего» до принятия трасс. Здесь шаг не начат, как только готовы конструкции.
 */
const floor3dStep = (step: IPipelineStep, walls: IPipelineStep): IPipelineStep =>
  step.state === 'blocked' && walls.state === 'done' ? { ...step, state: 'todo' } : step;

/**
 * Строки управления листом в порядке конвейера. Пока шаги после преобразования не доступны
 * (нет DXF, преобразование не готово), они показаны одной строкой на шаг без действий; иначе
 * шаги вида - по строке на вид.
 */
export const sheetRows = (
  projectId: string,
  revisionId: string,
  position: number,
  sheet: CadPipelineSheetRead,
): IPipelineRow[] => {
  const context: IContext = { projectId, revisionId, position, sheet };
  const merged = sheetSteps(sheet);
  const [calibration, convert, ...rest] = merged as [
    IPipelineStep,
    IPipelineStep,
    ...IPipelineStep[],
  ];
  const rows: IPipelineRow[] = [
    {
      id: 'calibration',
      key: 'calibration',
      view: null,
      viewLabel: null,
      step: calibration,
      stage: null,
      actions: calibrationActions(calibration, context),
    },
    {
      id: 'convert',
      key: 'convert',
      view: null,
      viewLabel: null,
      step: convert,
      stage: sheet.convert,
      actions: convertActions(convertStep(sheet), context),
    },
  ];

  const views = convert.state === 'done' ? sheet.views.filter((view) => view.has_dxf) : [];
  if (views.length === 0) {
    return [
      ...rows,
      ...rest.map((step) => ({
        id: step.key,
        key: step.key,
        view: null,
        viewLabel: null,
        step,
        stage: null,
        actions: [],
      })),
    ];
  }

  const several = views.length > 1;
  const perView = views.map((view) => ({ view, steps: viewSteps(view) }));
  for (const key of VIEW_KEYS) {
    for (const { view, steps } of perView) {
      const step = key === 'floor3d' ? floor3dStep(steps.floor3d, steps.walls) : steps[key];
      rows.push({
        id: `${key}:${view.view}`,
        key,
        view: view.view,
        viewLabel: several ? `Вид ${view.view}` : null,
        step,
        stage: stageOf(key, view),
        actions: viewActions(key, step, view, context),
      });
    }
  }
  return rows;
};

/** Подпись шага для кнопок: «Конструкции», «Зоны»… */
export const stepLabel = (key: PipelineStepKey): string => PIPELINE_STEP_LABELS[key];

const candidateOf = (row: IPipelineRow): IPipelineAction | null =>
  row.actions.find((item) => isMachineAction(item) && item.intent !== 'redo') ??
  row.actions.find((item) => item.kind === 'link') ??
  null;

const firstCandidate = (
  rows: readonly IPipelineRow[],
  states: readonly IPipelineStep['state'][],
): IPipelineNext | null => {
  for (const row of rows) {
    if (!states.includes(row.step.state)) continue;
    const found = candidateOf(row);
    if (found) return { row, action: found };
  }
  return null;
};

/**
 * Следующий шаг: сначала первый упавший, затем первый не начатый или ждущий человека, в порядке
 * конвейера. Машинное действие важнее перехода; необязательный 3D DXF в «следующие» не попадает.
 */
export const nextPipelineAction = (rows: readonly IPipelineRow[]): IPipelineNext | null => {
  const main = rows.filter((row) => row.key !== 'floor3d');
  return firstCandidate(main, ['failed']) ?? firstCandidate(main, ['todo', 'review']);
};
