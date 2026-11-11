import type {
  CadPipelineRead,
  CadPipelineSheetRead,
  CadPipelineStageRead,
  CadPipelineViewRead,
} from '@quantor/api-client';

import { cadCodeText } from './errors';

/**
 * Состояние конвейера листа CAD для показа (без UI): шаги, их состояния и одна строка итога.
 *
 * Конвейер листа: Калибровка (человек) -> CAD (`cad_pdf_convert`) -> автоматически Конструкции
 * и Зоны -> Одобрение (человек) -> Трассы -> 3D DXF (по требованию). Задания и итоги приходят с
 * сервера как есть; здесь только их свёртка в понятные состояния.
 */

export type PipelineStepKey =
  | 'calibration'
  | 'convert'
  | 'walls'
  | 'zones'
  | 'approval'
  | 'routes'
  | 'floor3d';

/**
 * `blocked` - предыдущий шаг не выполнен; `skipped` - шаг не нужен (преобразование не выпустило
 * DXF, видов для проверки нет); `review` - ждёт человека (одобрение вида, принятие трасс).
 */
export type PipelineStepState =
  | 'todo'
  | 'running'
  | 'done'
  | 'review'
  | 'failed'
  | 'skipped'
  | 'blocked';

export interface IPipelineStep {
  readonly key: PipelineStepKey;
  readonly label: string;
  readonly state: PipelineStepState;
  readonly detail: string | null;
}

export type PipelineTone = 'neutral' | 'accent' | 'success' | 'warning' | 'danger';

export interface IPipelineSummary {
  readonly tone: PipelineTone;
  readonly label: string;
}

export const PIPELINE_STEP_LABELS: Readonly<Record<PipelineStepKey, string>> = {
  calibration: 'Калибровка',
  convert: 'CAD',
  walls: 'Конструкции',
  zones: 'Зоны',
  approval: 'Одобрение',
  routes: 'Трассы',
  floor3d: '3D DXF',
};

const VIEW_KEYS = ['walls', 'zones', 'approval', 'routes', 'floor3d'] as const;
type ViewStepKey = (typeof VIEW_KEYS)[number];

const RESULT_NO_CAD = 'no_cad_review_required';
const RESULT_ZONES_SKIPPED = 'zones_skipped_existing';

const isActive = (stage: CadPipelineStageRead | null): boolean =>
  stage !== null && (stage.status === 'queued' || stage.status === 'running');

/** Чем «хуже» состояние, тем раньше оно в списке: при нескольких видах побеждает худшее. */
const SEVERITY: readonly PipelineStepState[] = [
  'failed',
  'running',
  'review',
  'todo',
  'blocked',
  'done',
  'skipped',
];

const severityOf = (state: PipelineStepState): number => SEVERITY.indexOf(state);

const make = (
  key: PipelineStepKey,
  state: PipelineStepState,
  detail: string | null = null,
): IPipelineStep => ({ key, label: PIPELINE_STEP_LABELS[key], state, detail });

const percentText = (stage: CadPipelineStageRead): string | null =>
  stage.progress === null
    ? null
    : `${Math.round(Math.min(Math.max(stage.progress, 0), 1) * 100)} %`;

/** Состояние этапа по последнему заданию: нет задания - `todo`. */
const stageState = (stage: CadPipelineStageRead | null): PipelineStepState => {
  if (stage === null) return 'todo';
  if (stage.status === 'queued' || stage.status === 'running') return 'running';
  if (stage.status !== 'succeeded' || stage.result_status === 'failed') return 'failed';
  return 'done';
};

const failureText = (stage: CadPipelineStageRead): string => {
  if (stage.error_code) return cadCodeText(stage.error_code);
  return stage.status === 'cancelled' ? 'Отменено' : 'Итог: отказ';
};

/** Подпись хода или причины отказа; у завершённого этапа - `null`. */
const stageDetail = (stage: CadPipelineStageRead | null): string | null => {
  if (stage === null) return null;
  const state = stageState(stage);
  if (state === 'running') return percentText(stage);
  if (state === 'failed') return failureText(stage);
  return null;
};

const stageStep = (key: PipelineStepKey, stage: CadPipelineStageRead | null): IPipelineStep =>
  make(key, stageState(stage), stageDetail(stage));

const zonesWord = (count: number): string => {
  const tail = count % 100;
  const last = count % 10;
  if (tail >= 11 && tail <= 14) return 'зон';
  if (last === 1) return 'зона';
  if (last >= 2 && last <= 4) return 'зоны';
  return 'зон';
};

const zonesStep = (view: CadPipelineViewRead): IPipelineStep => {
  const stage = view.zones;
  const state = stageState(stage);
  if (stage === null) {
    // Зоны могли разметить вручную, без автоматического задания.
    return view.zones_count > 0
      ? make('zones', 'done', `${view.zones_count} ${zonesWord(view.zones_count)}`)
      : make('zones', 'todo');
  }
  if (state !== 'done') return make('zones', state, stageDetail(stage));
  if (stage.result_status === RESULT_ZONES_SKIPPED) {
    return make('zones', 'done', 'на листе уже были зоны');
  }
  return make('zones', 'done', `${view.zones_count} ${zonesWord(view.zones_count)}`);
};

const approvalStep = (view: CadPipelineViewRead, walls: IPipelineStep, zones: IPipelineStep) => {
  if (view.approved) return make('approval', 'done');
  const ready = walls.state === 'done' && zones.state === 'done';
  return make('approval', ready ? 'review' : 'blocked', ready ? 'нужно решение человека' : null);
};

const routesStep = (view: CadPipelineViewRead): IPipelineStep => {
  const stage = view.routes;
  if (stage === null) return make('routes', view.approved ? 'todo' : 'blocked');
  const state = stageState(stage);
  if (state !== 'done') return make('routes', state, stageDetail(stage));
  return view.routes_accepted
    ? make('routes', 'done', 'приняты')
    : make('routes', 'review', 'ждут принятия');
};

const floor3dStep = (view: CadPipelineViewRead): IPipelineStep => {
  if (view.floor3d !== null) return stageStep('floor3d', view.floor3d);
  // Необязательный этап: без задания это не проблема, а «можно построить».
  return make('floor3d', view.routes_accepted ? 'todo' : 'blocked');
};

const viewSteps = (view: CadPipelineViewRead): Record<ViewStepKey, IPipelineStep> => {
  const walls = stageStep('walls', view.walls);
  const zones = zonesStep(view);
  return {
    walls,
    zones,
    approval: approvalStep(view, walls, zones),
    routes: routesStep(view),
    floor3d: floor3dStep(view),
  };
};

const convertStep = (sheet: CadPipelineSheetRead): IPipelineStep => {
  const stage = sheet.convert;
  if (stage === null) return make('convert', sheet.calibrated ? 'todo' : 'blocked');
  const step = stageStep('convert', stage);
  if (step.state === 'done' && stage.result_status === RESULT_NO_CAD) {
    return make('convert', 'done', 'DXF не выпущен');
  }
  return step;
};

const worst = (steps: readonly IPipelineStep[]): IPipelineStep => {
  const first = steps[0] as IPipelineStep;
  return steps.reduce(
    (best, step) => (severityOf(step.state) < severityOf(best.state) ? step : best),
    first,
  );
};

/**
 * Шаги листа в порядке конвейера. Виды с DXF сворачиваются по каждому шагу: побеждает худшее
 * состояние (ошибка, идёт, ждёт человека, не начато, заблокировано, готово). Пока преобразование
 * не выполнено, шаги после него заблокированы; если DXF не выпущен - пропущены.
 */
export const sheetSteps = (sheet: CadPipelineSheetRead): IPipelineStep[] => {
  const calibration = make('calibration', sheet.calibrated ? 'done' : 'todo');
  const convert = convertStep(sheet);

  if (convert.state !== 'done') {
    return [calibration, convert, ...VIEW_KEYS.map((key) => make(key, 'blocked'))];
  }

  const views = sheet.views.filter((view) => view.has_dxf);
  if (views.length === 0) {
    return [calibration, convert, ...VIEW_KEYS.map((key) => make(key, 'skipped'))];
  }

  const perView = views.map(viewSteps);
  const merged = VIEW_KEYS.map((key) => worst(perView.map((steps) => steps[key])));
  return [calibration, convert, ...merged];
};

const stateOf = (steps: readonly IPipelineStep[], key: PipelineStepKey): IPipelineStep =>
  steps.find((step) => step.key === key) ?? make(key, 'blocked');

const withProgress = (label: string, detail: string | null): string =>
  detail !== null && detail.endsWith('%') ? `${label}: ${detail}` : label;

/** Одна строка о состоянии листа: что с ним сейчас и нужно ли действие человека. */
export const sheetSummary = (sheet: CadPipelineSheetRead): IPipelineSummary => {
  const steps = sheetSteps(sheet);

  const failed = steps.find((step) => step.state === 'failed');
  if (failed) return { tone: 'danger', label: `Ошибка: ${failed.label}` };

  if (stateOf(steps, 'calibration').state === 'todo') {
    return { tone: 'warning', label: 'Нужна калибровка' };
  }

  const convert = stateOf(steps, 'convert');
  if (convert.state === 'running') {
    return { tone: 'accent', label: withProgress('CAD', convert.detail) };
  }
  if (convert.state === 'todo') return { tone: 'neutral', label: 'Готов к преобразованию в CAD' };
  if (convert.state === 'blocked') return { tone: 'neutral', label: 'CAD не запущен' };
  if (stateOf(steps, 'walls').state === 'skipped') {
    return { tone: 'neutral', label: 'CAD: DXF не выпущен' };
  }

  const walls = stateOf(steps, 'walls');
  const zones = stateOf(steps, 'zones');
  const auto = [walls, zones];
  if (auto.some((step) => step.state === 'running' || step.state === 'todo')) {
    return { tone: 'accent', label: 'Конструкции и зоны…' };
  }

  if (stateOf(steps, 'approval').state === 'review') {
    return { tone: 'warning', label: 'Ждёт одобрения' };
  }

  const routes = stateOf(steps, 'routes');
  if (routes.state === 'running') {
    return { tone: 'accent', label: withProgress('Трассы', routes.detail) };
  }
  if (routes.state === 'review') return { tone: 'warning', label: 'Трассы ждут принятия' };
  if (routes.state === 'todo') return { tone: 'neutral', label: 'Одобрен, трассы не построены' };
  if (routes.state === 'done') {
    return stateOf(steps, 'floor3d').state === 'running'
      ? { tone: 'accent', label: withProgress('3D DXF', stateOf(steps, 'floor3d').detail) }
      : { tone: 'success', label: 'Готово' };
  }

  return { tone: 'neutral', label: 'В работе' };
};

/** Хоть один этап хоть одного листа в очереди или идёт: ответ нужно опрашивать. */
export const pipelineHasActive = (data: CadPipelineRead | null | undefined): boolean =>
  (data?.sheets ?? []).some(
    (sheet) =>
      isActive(sheet.convert) ||
      sheet.views.some(
        (view) =>
          isActive(view.walls) ||
          isActive(view.zones) ||
          isActive(view.routes) ||
          isActive(view.floor3d),
      ),
  );
