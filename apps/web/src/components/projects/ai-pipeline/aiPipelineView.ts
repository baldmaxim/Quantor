import type {
  AiSheetStage2,
  AiSheetStyle,
  AiStageSummary,
  ProjectAiPipelineRead,
  ProjectAiSheetRow,
} from '@quantor/api-client';
import type { BadgeTone } from '@/components/ui';

/** Чистая логика шкалы этапов проекта: подписи, тона, строки этапа, расход. */

export type AiRowState = AiSheetStage2['state'];

export interface IBadge {
  readonly tone: BadgeTone;
  readonly label: string;
}

/** Бейдж этапа по сводке: идёт / готово / нужен человек / ошибки K. */
export const stageBadge = (stage: AiStageSummary): IBadge => {
  if (stage.status === 'running') return { tone: 'accent', label: 'Идёт' };
  if (stage.failed > 0) return { tone: 'danger', label: `Ошибки ${stage.failed}` };
  if (stage.needs_human > 0) return { tone: 'warning', label: 'Нужен человек' };
  if (stage.status === 'done') return { tone: 'success', label: 'Готово' };
  if (stage.status === 'attention') return { tone: 'warning', label: 'Не завершён' };
  return { tone: 'neutral', label: 'Не начат' };
};

/** «N из M листов» (склонение по знаменателю). */
export const stageProgressText = (stage: AiStageSummary): string => {
  const noun = stage.total % 10 === 1 && stage.total % 100 !== 11 ? 'листа' : 'листов';
  return `${stage.done} из ${stage.total} ${noun}`;
};

/** Расход Claude этапа; расход нигде не записан - `null`. */
export const costText = (stage: AiStageSummary): string | null => {
  if (stage.cost_usd === null || stage.cost_usd === undefined) return null;
  const money = `$${stage.cost_usd.toFixed(2)}`;
  return stage.duration_ms ? `${money} · ${Math.round(stage.duration_ms / 1000)} с` : money;
};

const STATE_BADGES: Readonly<Record<AiRowState, IBadge>> = {
  not_started: { tone: 'neutral', label: 'Не начато' },
  running: { tone: 'accent', label: 'Идёт' },
  ok: { tone: 'success', label: 'Готово' },
  attention: { tone: 'warning', label: 'Нужен человек' },
  failed: { tone: 'danger', label: 'Ошибка' },
};

const VERDICT_TEXT: Readonly<Record<string, string>> = {
  ready_for_human_review: 'готово к проверке человеком',
  needs_correction: 'нужны правки',
  insufficient_evidence: 'недостаточно данных',
};

export const verdictText = (verdict: string | null | undefined): string | null =>
  verdict ? (VERDICT_TEXT[verdict] ?? verdict) : null;

export interface IRowView {
  readonly badge: IBadge;
  /** Пояснение под названием листа: круг, вердикт, замечания. */
  readonly detail: string | null;
}

const stage2Detail = (stage: AiSheetStage2): string => {
  const parts = [`круг ${stage.rounds_done} из ${stage.rounds_max}`];
  const verdict = verdictText(stage.last_verdict);
  if (verdict) parts.push(stage.verdict_stale ? `${verdict} (до перестроения)` : verdict);
  if (stage.last_findings !== null && stage.last_findings !== undefined) {
    parts.push(`находок ${stage.last_findings}`);
  }
  if (stage.exhausted) parts.push('круги исчерпаны');
  return parts.join(' · ');
};

/** Оформление вида (роль Claude «оформление»): классы подписей штриховки и применённые регионы. */
export const styleDetail = (style: AiSheetStyle | null | undefined): string | null => {
  if (!style) return null;
  if (style.state === 'running') return 'Оформление: идёт';
  if (style.state === 'failed') {
    return style.error_message
      ? `Оформление: ошибка · ${style.error_message}`
      : 'Оформление: ошибка';
  }
  if (style.classes_found === null || style.classes_found === undefined) {
    return 'Оформление: ждёт запуска';
  }
  const parts = [`классов ${style.classes_found}`];
  if (style.regions_applied !== null && style.regions_applied !== undefined) {
    parts.push(`применено регионов ${style.regions_applied}`);
  }
  return `Оформление: ${parts.join(', ')}`;
};

/** Представление строки листа на этапе `stage`; `null` - лист в этап не входит. */
export const rowView = (row: ProjectAiSheetRow, stage: number): IRowView | null => {
  if (stage === 1) {
    return {
      badge: STATE_BADGES[row.stage1.state],
      detail: row.stage1.error_message ?? styleDetail(row.style),
    };
  }
  if (stage === 2) {
    const s = row.stage2;
    return s ? { badge: STATE_BADGES[s.state], detail: s.error_message ?? stage2Detail(s) } : null;
  }
  if (stage === 3) {
    const s = row.stage3;
    if (!s) return null;
    const parts = [
      s.claude_verdict ? `Claude: ${verdictText(s.claude_verdict)}` : null,
      s.codex_verdict ? `Codex: ${verdictText(s.codex_verdict)}` : null,
    ].filter((part): part is string => part !== null);
    return {
      badge: STATE_BADGES[s.state],
      detail: s.error_message ?? (parts.length > 0 ? parts.join(' · ') : null),
    };
  }
  const s = row.stage4;
  if (!s) return null;
  if (s.approved) return { badge: { tone: 'success', label: 'Одобрен' }, detail: null };
  return {
    badge: { tone: 'warning', label: 'Ждёт приёмки' },
    detail: s.open_remarks > 0 ? `Открытых замечаний: ${s.open_remarks}` : null,
  };
};

export interface IStageRow {
  readonly row: ProjectAiSheetRow;
  readonly view: IRowView;
}

/** Листы этапа с их представлением, в порядке ответа. */
export const stageRows = (data: ProjectAiPipelineRead, stage: number): readonly IStageRow[] =>
  data.sheets.flatMap((row) => {
    const view = rowView(row, stage);
    return view ? [{ row, view }] : [];
  });

/** Виды, где проверку Codex можно поставить сейчас. */
export const codexTargets = (data: ProjectAiPipelineRead): readonly ProjectAiSheetRow[] =>
  data.sheets.filter(
    (row) =>
      row.walls_job_id !== null &&
      row.stage3?.codex_available === true &&
      row.stage3.codex_running !== true,
  );
