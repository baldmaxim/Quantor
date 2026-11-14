'use client';

import type { FrameNodeOut, NodeStatus } from '@quantor/api-client';
import { useState, type FC } from 'react';

import { Button, EmptyState, StatusBadge, cx } from '@/components/ui';
import {
  NODE_STATUS_LABELS,
  NODE_STATUS_TONES,
  buildingLabel,
  elevationText,
  groupFrame,
  heightText,
  sectionLabel,
} from '@/lib/consistency/building-frame';
import { useBulkFrameStatus } from '@/lib/consistency/building-frame-queries';
import { errorMessage, extractCode, extractMessage } from '@/lib/errors';

import { FrameAddLevelDialog } from './FrameAddLevelDialog';
import { FrameLevelDialog } from './FrameLevelDialog';

/**
 * Дерево каркаса: корпус → секция → уровни снизу вверх. Выбор строк — пачкой подтвердить или
 * отклонить; «Подтвердить все кандидаты» — один проход по проекту. Уровень правится в диалоге.
 */

interface ITreeProps {
  readonly projectId: string;
  readonly nodes: readonly FrameNodeOut[];
}

const CELL = 'px-[var(--s-4)] py-[var(--s-3)] align-top text-sm';

const NodeHeader: FC<{
  readonly node: FrameNodeOut;
  readonly label: string;
  readonly selected: boolean;
  readonly onToggle: (id: string) => void;
  readonly level: 'building' | 'section';
}> = ({ node, label, selected, onToggle, level }) => (
  <div
    className={cx(
      'flex flex-wrap items-center gap-[var(--s-3)]',
      level === 'building' ? 'text-base font-semibold' : 'text-sm font-medium',
    )}
  >
    <label className="grid h-[28px] w-[28px] cursor-pointer place-items-center max-md:h-[44px] max-md:w-[44px]">
      <input
        type="checkbox"
        checked={selected}
        aria-label={`Выбрать: ${label}`}
        onChange={() => onToggle(node.id)}
        className="h-[16px] w-[16px] accent-[var(--accent)]"
      />
    </label>
    <span>{label}</span>
    <StatusBadge tone={NODE_STATUS_TONES[node.status]}>
      {NODE_STATUS_LABELS[node.status]}
    </StatusBadge>
    <span className="tabular text-xs font-normal text-muted">
      {node.origin === 'manual' ? 'добавлен вручную' : `листов: ${node.passport_count}`}
    </span>
  </div>
);

export const FrameTree: FC<ITreeProps> = ({ projectId, nodes }) => {
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [editing, setEditing] = useState<FrameNodeOut | null>(null);
  const [adding, setAdding] = useState(false);
  const bulk = useBulkFrameStatus(projectId);
  const groups = groupFrame(nodes);
  const candidates = nodes.filter((node) => node.status === 'candidate').map((node) => node.id);

  const toggle = (id: string) =>
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const apply = (ids: readonly string[], status: NodeStatus) =>
    bulk.mutate({ ids, status }, { onSuccess: () => setSelected(new Set()) });

  const bulkError = bulk.isError
    ? (extractMessage(bulk.error) ?? errorMessage(extractCode(bulk.error)))
    : null;

  return (
    <section aria-labelledby="frame-tree" className="flex flex-col gap-[var(--s-4)]">
      <div className="flex flex-wrap items-center gap-[var(--s-4)]">
        <h2 id="frame-tree" className="text-base font-semibold">
          Каркас
        </h2>
        <Button
          className="ml-auto max-sm:ml-0"
          disabled={candidates.length === 0 || bulk.isPending}
          onClick={() => apply(candidates, 'confirmed')}
        >
          Подтвердить все кандидаты ({candidates.length})
        </Button>
        <Button onClick={() => setAdding(true)}>Добавить уровень</Button>
      </div>

      {selected.size > 0 && (
        <div
          role="region"
          aria-label="Выбранные узлы"
          className="flex flex-wrap items-center gap-[var(--s-4)] rounded-[var(--radius-md)] border border-accent-soft bg-accent-soft px-[var(--s-5)] py-[var(--s-3)]"
        >
          <span className="tabular text-sm font-medium">Выбрано: {selected.size}</span>
          <Button
            variant="primary"
            loading={bulk.isPending}
            onClick={() => apply([...selected], 'confirmed')}
          >
            Подтвердить выбранные
          </Button>
          <Button
            variant="danger"
            disabled={bulk.isPending}
            onClick={() => apply([...selected], 'rejected')}
          >
            Отклонить выбранные
          </Button>
          <Button
            variant="ghost"
            disabled={bulk.isPending}
            onClick={() => apply([...selected], 'candidate')}
          >
            Вернуть в кандидаты
          </Button>
          <Button variant="ghost" disabled={bulk.isPending} onClick={() => setSelected(new Set())}>
            Снять выбор
          </Button>
        </div>
      )}
      {bulkError && (
        <p role="alert" className="text-sm text-danger">
          {bulkError}
        </p>
      )}

      {groups.length === 0 && (
        <EmptyState
          compact
          title="Каркаса пока нет"
          description="Подтвердите паспорта листов-планов и нажмите «Собрать из паспортов»."
        />
      )}

      {groups.map(({ building, sections }) => (
        <div
          key={building.id}
          className="flex flex-col gap-[var(--s-4)] rounded-[var(--radius-md)] border border-border bg-surface px-[var(--s-5)] py-[var(--s-4)]"
        >
          <NodeHeader
            node={building}
            label={buildingLabel(building.building)}
            selected={selected.has(building.id)}
            onToggle={toggle}
            level="building"
          />
          {sections.map(({ section, levels }) =>
            section === null ? null : (
              <div key={section.id} className="flex flex-col gap-[var(--s-3)]">
                <NodeHeader
                  node={section}
                  label={sectionLabel(section.section)}
                  selected={selected.has(section.id)}
                  onToggle={toggle}
                  level="section"
                />
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[640px] border-collapse">
                    <thead>
                      <tr className="border-b border-border text-left text-xs text-muted">
                        <th className={CELL}>
                          <span className="sr-only">Выбор</span>
                        </th>
                        <th className={CELL}>Уровень</th>
                        <th className={CELL}>Номер</th>
                        <th className={CELL}>Отметка</th>
                        <th className={CELL}>Высота</th>
                        <th className={CELL}>Листов</th>
                        <th className={CELL}>Статус</th>
                        <th className={CELL}>
                          <span className="sr-only">Действия</span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {levels.map((level) => (
                        <tr
                          key={level.id}
                          data-testid="frame-level"
                          className={cx(
                            'border-b border-border last:border-b-0',
                            selected.has(level.id) && 'bg-accent-soft',
                          )}
                        >
                          <td className={CELL}>
                            <label className="grid h-[28px] w-[28px] cursor-pointer place-items-center max-md:h-[44px] max-md:w-[44px]">
                              <input
                                type="checkbox"
                                checked={selected.has(level.id)}
                                aria-label={`Выбрать: ${level.code ?? ''}`}
                                onChange={() => toggle(level.id)}
                                className="h-[16px] w-[16px] accent-[var(--accent)]"
                              />
                            </label>
                          </td>
                          <td className={CELL}>{level.code}</td>
                          <td className={`${CELL} tabular`}>{level.ordinal ?? '—'}</td>
                          <td className={`${CELL} tabular`}>
                            {level.elevation_values.length > 1 ? (
                              <StatusBadge tone="warning" wrap>
                                Разные: {level.elevation_values.map(elevationText).join('; ')}
                              </StatusBadge>
                            ) : (
                              elevationText(level.elevation_m)
                            )}
                            {level.manual_fields.includes('elevation_m') && (
                              <span className="ml-[var(--s-2)] text-xs text-muted">вручную</span>
                            )}
                          </td>
                          <td className={`${CELL} tabular`}>
                            {level.height_m !== null ? (
                              <>
                                {heightText(level.height_m)}{' '}
                                <span className="text-xs text-muted">вручную</span>
                              </>
                            ) : level.height_derived_m !== null ? (
                              <>
                                {heightText(level.height_derived_m)}{' '}
                                <span className="text-xs text-muted">по отметкам</span>
                              </>
                            ) : (
                              '—'
                            )}
                          </td>
                          <td className={`${CELL} tabular`}>
                            {level.origin === 'manual' && level.passport_count === 0
                              ? 'вручную'
                              : level.passport_count}
                          </td>
                          <td className={CELL}>
                            <StatusBadge tone={NODE_STATUS_TONES[level.status]}>
                              {NODE_STATUS_LABELS[level.status]}
                            </StatusBadge>
                          </td>
                          <td className={CELL}>
                            <Button
                              compact
                              onClick={() => setEditing(level)}
                              aria-label={`Править: ${level.code ?? ''}`}
                            >
                              Править
                            </Button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ),
          )}
        </div>
      ))}

      {editing && (
        <FrameLevelDialog projectId={projectId} level={editing} onClose={() => setEditing(null)} />
      )}
      {adding && <FrameAddLevelDialog projectId={projectId} onClose={() => setAdding(false)} />}
    </section>
  );
};
