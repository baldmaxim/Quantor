'use client';

import type { FC, ReactNode } from 'react';

import { StatusBadge } from '@/components/ui';
import {
  candidateNote,
  candidateTitle,
  isSelectable,
  type ICorpsGroup,
} from '@/lib/tender/candidates';

/**
 * Дерево этажей выпуска базы: корпус → секция → этаж. Флажок корпуса и секции переключает все
 * доступные этажи внутри. Недоступные (нет кадра или DXF) отключены и подписаны причиной;
 * несовмещённые с осями — доступны, но по умолчанию не отмечены.
 */

interface ITreeProps {
  readonly groups: readonly ICorpsGroup[];
  readonly selected: ReadonlySet<string>;
  readonly onToggle: (keys: readonly string[], on: boolean) => void;
}

const Check: FC<{
  readonly label: string;
  readonly checked: boolean;
  readonly indeterminate?: boolean;
  readonly disabled?: boolean;
  readonly onChange: (on: boolean) => void;
}> = ({ label, checked, indeterminate = false, disabled = false, onChange }) => (
  <input
    type="checkbox"
    aria-label={label}
    checked={checked}
    disabled={disabled}
    ref={(node) => {
      if (node) node.indeterminate = indeterminate;
    }}
    onChange={(event) => onChange(event.target.checked)}
    className="h-[16px] w-[16px] accent-[var(--accent)]"
  />
);

const Box: FC<{ readonly children: ReactNode }> = ({ children }) => (
  <span className="grid h-[28px] w-[28px] shrink-0 place-items-center max-md:h-[44px] max-md:w-[44px]">
    {children}
  </span>
);

const state = (keys: readonly string[], selected: ReadonlySet<string>) => {
  const on = keys.filter((key) => selected.has(key)).length;
  return { checked: keys.length > 0 && on === keys.length, mixed: on > 0 && on < keys.length };
};

export const CandidateTree: FC<ITreeProps> = ({ groups, selected, onToggle }) => (
  <div className="flex flex-col gap-[var(--s-5)]">
    {groups.map((corps) => {
      const corpsKeys = corps.sections.flatMap((section) =>
        section.floors.filter(isSelectable).map((floor) => floor.view_key),
      );
      const corpsState = state(corpsKeys, selected);
      return (
        <div key={corps.key} className="flex flex-col gap-[var(--s-3)]">
          <label className="flex items-center gap-[var(--s-3)] text-base font-semibold">
            <Box>
              <Check
                label={`Выбрать: ${corps.label}`}
                checked={corpsState.checked}
                indeterminate={corpsState.mixed}
                disabled={corpsKeys.length === 0}
                onChange={(on) => onToggle(corpsKeys, on)}
              />
            </Box>
            {corps.label}
          </label>
          {corps.sections.map((section) => {
            const keys = section.floors.filter(isSelectable).map((floor) => floor.view_key);
            const sectionState = state(keys, selected);
            return (
              <div key={section.key} className="ml-[var(--s-6)] flex flex-col gap-[var(--s-2)]">
                <label className="flex items-center gap-[var(--s-3)] text-sm font-medium">
                  <Box>
                    <Check
                      label={`Выбрать: ${corps.label}, ${section.label}`}
                      checked={sectionState.checked}
                      indeterminate={sectionState.mixed}
                      disabled={keys.length === 0}
                      onChange={(on) => onToggle(keys, on)}
                    />
                  </Box>
                  {section.label}
                </label>
                <ul className="m-0 ml-[var(--s-6)] flex list-none flex-col gap-[var(--s-1)] p-0">
                  {section.floors.map((floor) => {
                    const note = candidateNote(floor);
                    const selectable = isSelectable(floor);
                    return (
                      <li key={floor.view_key}>
                        <label className="flex items-start gap-[var(--s-3)] text-sm">
                          <Box>
                            <Check
                              label={`Включить: ${candidateTitle(floor)}`}
                              checked={selected.has(floor.view_key)}
                              disabled={!selectable}
                              onChange={(on) => onToggle([floor.view_key], on)}
                            />
                          </Box>
                          <span className="flex min-w-0 flex-1 flex-col pt-[var(--s-2)]">
                            <span className="[overflow-wrap:anywhere]">
                              {candidateTitle(floor)}
                              <span className="ml-[var(--s-3)] text-xs text-muted">
                                {floor.document_title}
                              </span>
                            </span>
                            {note && (
                              <span>
                                <StatusBadge tone={selectable ? 'warning' : 'danger'}>
                                  {note}
                                </StatusBadge>
                              </span>
                            )}
                          </span>
                        </label>
                      </li>
                    );
                  })}
                </ul>
              </div>
            );
          })}
        </div>
      );
    })}
  </div>
);
