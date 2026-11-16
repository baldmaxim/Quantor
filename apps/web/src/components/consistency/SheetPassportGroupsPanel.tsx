'use client';

import type { SheetPassportGroupOut } from '@quantor/api-client';
import { useState, type FC } from 'react';

import { Button } from '@/components/ui';
import { errorMessage, extractCode, extractMessage } from '@/lib/errors';
import {
  useGroupPassportStatus,
  useSheetPassportGroups,
} from '@/lib/consistency/sheet-passport-queries';
import { sheetKindLabel } from '@/lib/consistency/sheet-passports';

/**
 * Группы листов (ADR-0043, С1): раздел · тип · корпус · секция со счётчиками статусов.
 *
 * Человек смотрит группу («Показать» ставит фильтры таблицы) и подтверждает её целиком. Сервер
 * подтверждает только кандидатов: отклонённый человеком лист группа не перебивает.
 */

interface IPanelProps {
  readonly projectId: string;
  readonly onShow: (group: SheetPassportGroupOut) => void;
}

const FLOOR_PLAN = 'floor_plan';

const CELL = 'px-[var(--s-4)] py-[var(--s-2)]';

const groupKey = (group: SheetPassportGroupOut): string =>
  [group.section_mark, group.sheet_kind, group.building, group.section]
    .map((value) => value ?? '∅')
    .join('|');

export const groupLabel = (group: SheetPassportGroupOut): string =>
  [
    group.section_mark ?? 'раздел не указан',
    sheetKindLabel(group.sheet_kind),
    group.building ? `корпус ${group.building}` : 'корпус не указан',
    group.section ? `секция ${group.section}` : 'секция не указана',
  ].join(' · ');

const Value: FC<{ readonly value: string | null }> = ({ value }) =>
  value === null ? <span className="text-muted">не указан</span> : <>{value}</>;

export const SheetPassportGroupsPanel: FC<IPanelProps> = ({ projectId, onShow }) => {
  const [floorOnly, setFloorOnly] = useState(true);
  const groups = useSheetPassportGroups(projectId, floorOnly ? FLOOR_PLAN : null, true);
  const status = useGroupPassportStatus(projectId);
  const rows = groups.data?.groups ?? [];
  const error = status.error ?? groups.error;

  return (
    <section
      aria-labelledby="passport-groups"
      className="flex flex-col gap-[var(--s-3)] rounded-[var(--radius-md)] border border-border bg-surface px-[var(--s-5)] py-[var(--s-4)]"
    >
      <div className="flex flex-wrap items-center gap-[var(--s-4)]">
        <h2 id="passport-groups" className="text-base font-semibold">
          Группы листов
        </h2>
        <p className="min-w-0 flex-1 basis-[16rem] text-xs text-muted">
          Листы с одинаковыми разделом, типом, корпусом и секцией. «Показать» открывает листы группы
          в таблице, «Подтвердить» подтверждает всех кандидатов группы. Для проверок нужны планы
          этажей проверяемой секции.
        </p>
        <label className="flex items-center gap-[var(--s-2)] text-sm">
          <input
            type="checkbox"
            className="h-[16px] w-[16px] accent-[var(--accent)]"
            checked={floorOnly}
            onChange={(event) => setFloorOnly(event.target.checked)}
          />
          Только планы этажей
        </label>
      </div>
      {groups.data && rows.length === 0 && (
        <p className="text-sm text-muted">Групп нет: листы ещё не разобраны.</p>
      )}
      {rows.length > 0 && (
        <div className="max-h-[24rem] overflow-auto overscroll-contain rounded-[var(--radius-sm)] border border-border">
          <table className="w-full min-w-[48rem] border-collapse text-left text-sm">
            <thead className="sticky top-0 bg-surface-muted text-micro font-semibold tracking-[0.06em] text-muted uppercase">
              <tr>
                <th scope="col" className={CELL}>
                  Раздел
                </th>
                {!floorOnly && (
                  <th scope="col" className={CELL}>
                    Тип
                  </th>
                )}
                <th scope="col" className={CELL}>
                  Корпус
                </th>
                <th scope="col" className={CELL}>
                  Секция
                </th>
                <th scope="col" className={`${CELL} text-right`}>
                  Листов
                </th>
                <th scope="col" className={`${CELL} text-right`}>
                  Без этажа
                </th>
                <th scope="col" className={`${CELL} text-right`}>
                  Подтверждено
                </th>
                <th scope="col" className={CELL}>
                  <span className="visually-hidden">Действия</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map((group) => (
                <tr key={groupKey(group)} data-testid="passport-group">
                  <td className={CELL}>
                    <Value value={group.section_mark} />
                  </td>
                  {!floorOnly && <td className={CELL}>{sheetKindLabel(group.sheet_kind)}</td>}
                  <td className={CELL}>
                    <Value value={group.building} />
                  </td>
                  <td className={CELL}>
                    <Value value={group.section} />
                  </td>
                  <td className={`${CELL} tabular text-right`}>{group.total}</td>
                  <td className={`${CELL} tabular text-right`}>{group.without_levels || '—'}</td>
                  <td className={`${CELL} tabular text-right`}>
                    {group.confirmed} из {group.total}
                  </td>
                  <td className={CELL}>
                    <div className="flex justify-end gap-[var(--s-2)]">
                      <Button
                        compact
                        onClick={() => onShow(group)}
                        aria-label={`Показать: ${groupLabel(group)}`}
                      >
                        Показать
                      </Button>
                      {group.candidate > 0 && (
                        <Button
                          compact
                          variant="primary"
                          disabled={status.isPending}
                          onClick={() => status.mutate({ group, status: 'confirmed' })}
                          aria-label={`Подтвердить ${group.candidate}: ${groupLabel(group)}`}
                        >
                          Подтвердить {group.candidate}
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {error !== null && (
        <p role="alert" className="text-sm text-danger">
          {extractMessage(error) ?? errorMessage(extractCode(error))}
        </p>
      )}
    </section>
  );
};
