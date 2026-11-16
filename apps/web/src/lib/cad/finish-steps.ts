import type {
  CadFinishSheetRead,
  CadFinishTemplateRead,
  CadFinishWarningRead,
} from '@quantor/api-client';

import { DASH } from './finish-sheet';
import { ROOM_TYPE_LABELS, type FinishWarningCode, type RoomType } from './room-types';

/**
 * Готовность шагов раздела «Отделка»: зоны с типом -> шаблоны -> шаблон у зоны -> ведомость.
 * Здесь считаются только зоны и шаблоны для индикации; количества отделки считает сервер.
 * Пока ведомость или шаблоны не загружены, шаг нейтрален и число - «—», не 0. Чистая логика.
 */

export type FinishStepStatus = 'ready' | 'action' | 'neutral';

export const FINISH_STEP_STATUS_LABELS: Readonly<Record<FinishStepStatus, string>> = {
  ready: 'готово',
  action: 'нужно действие',
  neutral: 'нет данных',
};

export interface IFinishStep {
  readonly status: FinishStepStatus;
  /** Строка-итог цифрами. */
  readonly summary: string;
  /** Что сделать; `null` - делать нечего или данных ещё нет. */
  readonly hint: string | null;
}

export interface IFinishSteps {
  /** Нет калибровки: площадей нет вообще, плашка над шагами. */
  readonly calibration: CadFinishWarningRead | null;
  readonly zones: IFinishStep & { readonly untypedIds: readonly string[] };
  readonly templates: IFinishStep & {
    readonly uncoveredTypes: readonly RoomType[];
    /** Шаг готов: список шаблонов сворачивается, ведомость остаётся на экране. */
    readonly collapsed: boolean;
  };
  readonly assignment: IFinishStep & { readonly withoutTemplateIds: readonly string[] };
  /** `warnings` - предупреждения ведомости без переехавших в плашку и в шаг 3. */
  readonly sheet: IFinishStep & { readonly warnings: readonly CadFinishWarningRead[] };
}

/** С этими предупреждениями ведомость не считается готовой. */
export const BLOCKING_WARNING_CODES: readonly FinishWarningCode[] = [
  'calibration_missing',
  'geometry_issue',
  'wall_height_missing',
  'no_template',
];

/** Показаны вне общего блока предупреждений: в плашке над шагами и в шаге 3. */
const MOVED_WARNING_CODES: readonly FinishWarningCode[] = ['calibration_missing', 'no_template'];

const NEUTRAL = (summary: string): IFinishStep => ({ status: 'neutral', summary, hint: null });

/**
 * Зоны, которым отделка не считается по принятому ответу к документации («квартиры без отделки»):
 * тип и шаблон от них не требуются.
 */
const withoutFinishIds = (sheet: CadFinishSheetRead): ReadonlySet<string> =>
  new Set(
    sheet.warnings
      .filter((warning) => warning.code === 'apartment_without_finish')
      .flatMap((warning) => warning.zone_ids),
  );

export const buildFinishSteps = (
  sheet: CadFinishSheetRead | undefined,
  templates: readonly CadFinishTemplateRead[] | undefined,
): IFinishSteps => {
  const skipped = sheet === undefined ? new Set<string>() : withoutFinishIds(sheet);
  const required = sheet?.zones.filter((zone) => !skipped.has(zone.zone_id)) ?? [];
  const untypedIds = required.filter((zone) => zone.room_type === null).map((z) => z.zone_id);
  const withoutTemplate = required.filter((zone) => zone.template_id === null);
  const withoutTemplateIds = withoutTemplate.map((zone) => zone.zone_id);

  // Шаг 1: зоны-помещения и их типы.
  let zonesStep: IFinishStep = NEUTRAL(`Помещений на листе: ${DASH}`);
  if (sheet !== undefined) {
    const total = sheet.zones.length;
    const summary =
      `Помещений на листе: ${total} · без типа: ${untypedIds.length}` +
      (skipped.size > 0 ? ` · без отделки: ${skipped.size}` : '');
    if (total === 0) {
      zonesStep = {
        status: 'action',
        summary,
        hint: 'На листе нет зон-помещений: разметьте их в разделе «Зоны»',
      };
    } else if (untypedIds.length > 0) {
      zonesStep = {
        status: 'action',
        summary,
        hint: 'Задайте тип помещения — по нему подбирается шаблон',
      };
    } else {
      zonesStep = { status: 'ready', summary, hint: null };
    }
  }

  // Шаг 2: шаблоны проекта. Непокрытый тип - тип зоны без шаблона, которого нет ни в одном шаблоне.
  const covered = new Set<RoomType>((templates ?? []).flatMap((item) => item.room_types));
  const uncoveredTypes: RoomType[] = [];
  if (templates !== undefined) {
    for (const zone of withoutTemplate) {
      const type = zone.room_type;
      if (type !== null && !covered.has(type) && !uncoveredTypes.includes(type)) {
        uncoveredTypes.push(type);
      }
    }
  }
  let templatesStep: IFinishStep = NEUTRAL(`Шаблонов: ${DASH}`);
  if (templates !== undefined) {
    const summary = `Шаблонов: ${templates.length}`;
    if (templates.length === 0) {
      templatesStep = {
        status: 'action',
        summary,
        hint: 'Создайте шаблон: слои пола, стен и потолка для типа помещения',
      };
    } else if (sheet === undefined) {
      // Типы зон листа неизвестны: покрытие не проверить.
      templatesStep = NEUTRAL(summary);
    } else if (uncoveredTypes.length > 0) {
      templatesStep = {
        status: 'action',
        summary,
        hint: `Нет шаблона для типов: ${uncoveredTypes.map((type) => ROOM_TYPE_LABELS[type]).join(', ')}`,
      };
    } else {
      templatesStep = { status: 'ready', summary, hint: null };
    }
  }

  // Шаг 3: шаблон у каждой зоны, которой отделка считается.
  let assignmentStep: IFinishStep = NEUTRAL(`С шаблоном: ${DASH}`);
  if (sheet !== undefined && required.length > 0) {
    const withTemplate = required.filter((zone) => zone.template_id !== null);
    const byType = withTemplate.filter((zone) => zone.template_source === 'by_type').length;
    const explicit = withTemplate.filter((zone) => zone.template_source === 'explicit').length;
    const summary = `С шаблоном: ${withTemplate.length} из ${required.length} (по типу: ${byType}, явно: ${explicit})`;
    assignmentStep =
      withoutTemplateIds.length > 0
        ? {
            status: 'action',
            summary,
            hint: 'Шаблон подбирается по типу помещения автоматически. Назначить другой шаблон выбранным зонам — в разделе «Зоны»',
          }
        : { status: 'ready', summary, hint: null };
  }

  // Шаг 4: ведомость.
  let sheetStep: IFinishStep = NEUTRAL(`Итоговых строк: ${DASH}`);
  if (sheet !== undefined) {
    const blocking = sheet.warnings.filter((w) => BLOCKING_WARNING_CODES.includes(w.code));
    const summary = `Итоговых строк: ${sheet.totals.length} · предупреждений: ${sheet.warnings.length}`;
    if (blocking.length > 0) {
      sheetStep = {
        status: 'action',
        summary,
        hint: 'Количества неполные: устраните предупреждения',
      };
    } else if (sheet.totals.length === 0) {
      sheetStep = {
        status: 'action',
        summary,
        hint: 'Количеств пока нет: проверьте шаги 1–3 и слои в шаблонах',
      };
    } else {
      sheetStep = { status: 'ready', summary, hint: null };
    }
  }

  return {
    calibration: sheet?.warnings.find((w) => w.code === 'calibration_missing') ?? null,
    zones: { ...zonesStep, untypedIds },
    templates: { ...templatesStep, uncoveredTypes, collapsed: templatesStep.status === 'ready' },
    assignment: { ...assignmentStep, withoutTemplateIds },
    sheet: {
      ...sheetStep,
      warnings: sheet?.warnings.filter((w) => !MOVED_WARNING_CODES.includes(w.code)) ?? [],
    },
  };
};
