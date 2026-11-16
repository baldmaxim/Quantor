'use client';

import type {
  AlignResult,
  AlignScaleSource,
  AlignmentStatus,
  PlanAlignmentOut,
  PlanAlignmentsOut,
} from '@quantor/api-client';
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, type FC } from 'react';

import { Button, ProgressRow, StatusBadge, type BadgeTone } from '@/components/ui';
import { frameKeys } from '@/lib/consistency/building-frame-queries';
import {
  isAlignActive,
  useBulkAlignmentStatus,
  usePlanAlignments,
  useStartPlanAlign,
} from '@/lib/consistency/plan-alignment-queries';
import { errorMessage, extractCode, extractMessage } from '@/lib/errors';

/**
 * Совмещение планов с уровнем (С3): виды CAD подтверждённых планов этажей переводятся в систему
 * координат эталонного плана АР секции по маркам осей. В проверки идёт подтверждённое совмещение.
 */

interface IPanelProps {
  readonly projectId: string;
}

const RESULT_VIEWS: Record<AlignResult, { readonly label: string; readonly tone: BadgeTone }> = {
  reference: { label: 'Эталон секции', tone: 'accent' },
  aligned: { label: 'Совмещён', tone: 'success' },
  check: { label: 'Проверить', tone: 'warning' },
  failed: { label: 'Не совмещён', tone: 'danger' },
  not_run: { label: 'Не совмещался', tone: 'neutral' },
};

const STATUS_LABELS: Record<AlignmentStatus, string> = {
  candidate: 'Кандидат',
  confirmed: 'Подтверждено',
  rejected: 'Отклонено',
};

const SCALE_LABELS: Record<AlignScaleSource, string> = {
  calibration: 'калибровка человеком',
  dimension_chains: 'размерные цепочки',
};

// Подтвердить пачкой можно только совмещённое без замечаний; «проверить» - по одному.
const CLEAN: ReadonlySet<AlignResult> = new Set<AlignResult>(['reference', 'aligned']);

const num = (value: number | null | undefined): string => (value == null ? '—' : String(value));

const mm = (value: number | null): string => (value === null ? '—' : `${Math.round(value)} мм`);

export const scopeLabel = (building: string | null, section: string | null): string => {
  const parts = [building ? `Корпус ${building}` : '', section ? `секция ${section}` : ''];
  return parts.filter(Boolean).join(' · ') || 'Корпус и секция не указаны';
};

const sheetLabel = (row: PlanAlignmentOut): string => {
  const mark = row.section_mark ? `${row.section_mark} · ` : '';
  const view = row.view > 0 ? ` · вид ${row.view}` : '';
  return `${mark}${row.file_name} · лист ${row.page_index + 1}${view}`;
};

const levelsLabel = (row: PlanAlignmentOut): string | null => {
  if (!row.level_from) return null;
  return row.level_to && row.level_to !== row.level_from
    ? `уровни ${row.level_from}–${row.level_to}`
    : `уровень ${row.level_from}`;
};

const transformText = (row: PlanAlignmentOut): string | null => {
  if (row.result === 'reference') return 'Задаёт систему координат секции';
  if (row.dx_mm === null || row.dy_mm === null) return null;
  return `Поворот ${num(row.rotation_deg)}° · сдвиг ${mm(row.dx_mm)}, ${mm(row.dy_mm)} · оси ${
    row.agreed_axes
  } из ${row.common_axes} · невязка ${mm(row.residual_rms_mm)} (макс. ${mm(row.residual_max_mm)})`;
};

const AlignmentItem: FC<{
  readonly row: PlanAlignmentOut;
  readonly busy: boolean;
  readonly onStatus: (id: string, status: AlignmentStatus) => void;
}> = ({ row, busy, onStatus }) => {
  const view = RESULT_VIEWS[row.result];
  const levels = levelsLabel(row);
  const transform = transformText(row);
  return (
    <li data-testid="plan-alignment" className="flex flex-col gap-[var(--s-2)] py-[var(--s-3)]">
      <div className="flex flex-wrap items-center gap-[var(--s-3)]">
        <StatusBadge tone={view.tone}>{view.label}</StatusBadge>
        <span className="text-sm font-medium [overflow-wrap:anywhere]">{sheetLabel(row)}</span>
        <span className="text-xs text-muted">
          {levels && `${levels} · `}
          {STATUS_LABELS[row.status]}
          {row.scale_source && ` · масштаб: ${SCALE_LABELS[row.scale_source]}`}
        </span>
        <div className="ml-auto flex flex-wrap gap-[var(--s-2)] max-sm:ml-0">
          {row.status === 'candidate' ? (
            <>
              <Button
                compact
                variant="primary"
                disabled={busy}
                onClick={() => onStatus(row.id, 'confirmed')}
              >
                Принять
              </Button>
              <Button compact disabled={busy} onClick={() => onStatus(row.id, 'rejected')}>
                Отклонить
              </Button>
            </>
          ) : (
            <Button compact disabled={busy} onClick={() => onStatus(row.id, 'candidate')}>
              Вернуть в кандидаты
            </Button>
          )}
        </div>
      </div>
      {transform && <p className="tabular text-xs text-muted">{transform}</p>}
      {row.axes.length > 0 && row.result !== 'reference' && (
        <p className="text-xs text-muted [overflow-wrap:anywhere]">
          Совпали оси: {row.axes.join(', ')}
        </p>
      )}
      {row.reasons.length > 0 && (
        <ul className="flex list-disc flex-col gap-[var(--s-1)] pl-[var(--s-5)] text-xs">
          {row.reasons.map((reason) => (
            <li key={reason} className="[overflow-wrap:anywhere]">
              {reason}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
};

const Summary: FC<{ readonly data: PlanAlignmentsOut }> = ({ data }) => {
  const run = data.last_run;
  if (run?.status !== 'succeeded') return null;
  return (
    <p className="tabular text-sm text-muted" data-testid="align-summary">
      Планов: {num(run.plans)} · видов: {num(run.views)} · совмещено: {num(run.aligned)} ·
      проверить: {num(run.check)} · не совмещено: {num(run.failed)} · не совмещалось:{' '}
      {num(run.not_run)}
      {(run.without_cad ?? 0) > 0 && ` · без CAD: ${run.without_cad}`}
    </p>
  );
};

const groupRows = (rows: readonly PlanAlignmentOut[]): [string, PlanAlignmentOut[]][] => {
  const groups = new Map<string, PlanAlignmentOut[]>();
  for (const row of rows) {
    const key = scopeLabel(row.building, row.section);
    groups.set(key, [...(groups.get(key) ?? []), row]);
  }
  return [...groups.entries()];
};

export const FramePlanAlignPanel: FC<IPanelProps> = ({ projectId }) => {
  const alignments = usePlanAlignments(projectId, true);
  const start = useStartPlanAlign(projectId);
  const bulk = useBulkAlignmentStatus(projectId);
  const client = useQueryClient();
  const data = alignments.data;
  const active = isAlignActive(data);

  // Конец задания меняет проверку «план ↔ уровень»: перечитываем каркас.
  const wasActive = useRef(false);
  useEffect(() => {
    if (wasActive.current && !active) {
      void client.invalidateQueries({ queryKey: frameKeys.project(projectId) });
    }
    wasActive.current = active;
  }, [active, client, projectId]);

  const clean = (data?.alignments ?? [])
    .filter((row) => row.status === 'candidate' && CLEAN.has(row.result))
    .map((row) => row.id);
  const error = start.error ?? bulk.error ?? alignments.error;

  return (
    <section
      aria-labelledby="plan-alignments"
      className="flex flex-col gap-[var(--s-3)] rounded-[var(--radius-md)] border border-border bg-surface px-[var(--s-5)] py-[var(--s-4)]"
    >
      <div className="flex flex-wrap items-center gap-[var(--s-4)]">
        <h2 id="plan-alignments" className="text-base font-semibold">
          Совмещение планов с уровнем
        </h2>
        <p className="min-w-0 flex-1 basis-[14rem] text-xs text-muted">
          Планы любого раздела переводятся в систему координат эталонного плана АР секции по маркам
          осей из CAD. Нужны подтверждённые паспорта планов и листы, преобразованные в CAD.
          {data &&
            ` Допуск марки — ${data.params.axis_agree_mm} мм, порог невязки — ${data.params.residual_check_mm} мм.`}
        </p>
        <Button
          variant="primary"
          loading={start.isPending}
          disabled={active}
          onClick={() => start.mutate()}
        >
          Совместить планы
        </Button>
      </div>
      {active && <ProgressRow value={data?.last_run?.progress ?? null} label="Совмещение планов" />}
      {data?.last_run?.status === 'failed' && (
        <p role="alert" className="text-sm text-danger">
          {errorMessage(data.last_run.error_code ?? '')}
        </p>
      )}
      {data && <Summary data={data} />}
      {data && data.alignments.length === 0 && data.last_run?.status === 'succeeded' && (
        <p className="text-sm text-muted">
          Подтверждённых паспортов планов этажей нет: подтвердите паспорта в таблице листов.
        </p>
      )}
      {data && data.alignments.length > 0 && (
        <>
          {clean.length > 0 && (
            <div>
              <Button
                compact
                disabled={bulk.isPending}
                onClick={() => bulk.mutate({ ids: clean, status: 'confirmed' })}
              >
                Принять совмещённые без замечаний ({clean.length})
              </Button>
            </div>
          )}
          {groupRows(data.alignments).map(([scope, rows]) => (
            <div key={scope} className="flex flex-col">
              <h3 className="text-sm font-semibold">{scope}</h3>
              <ul className="divide-y divide-border">
                {rows.map((row) => (
                  <AlignmentItem
                    key={row.id}
                    row={row}
                    busy={bulk.isPending}
                    onStatus={(id, status) => bulk.mutate({ ids: [id], status })}
                  />
                ))}
              </ul>
            </div>
          ))}
        </>
      )}
      {error !== null && (
        <p role="alert" className="text-sm text-danger">
          {extractMessage(error) ?? errorMessage(extractCode(error))}
        </p>
      )}
    </section>
  );
};
