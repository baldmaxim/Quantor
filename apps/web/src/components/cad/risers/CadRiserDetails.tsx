'use client';

import type { RiserServes, RiserValve } from '@quantor/api-client';
import { useId, useState, type FC } from 'react';

import { ClearableInput } from '@/components/ui/ClearableInput';
import {
  RISER_SERVES,
  RISER_SERVES_LABELS,
  RISER_VALVES,
  RISER_VALVE_LABELS,
  hasDetails,
  type IRiserDraft,
  type IRiserProblems,
} from '@/lib/cad/risers';

import { LABEL, Problem, SELECT } from './riser-ui';

interface IProps {
  readonly title: string;
  readonly draft: IRiserDraft;
  readonly problems: IRiserProblems | null;
  readonly disabled: boolean;
  readonly onChange: (patch: Partial<IRiserDraft>) => void;
}

/**
 * Раскрываемый блок «Подробнее»: этажи от-до, назначение, клапан, предел огнестойкости (EI).
 * Раскрыт, если поля заполнены или в них ошибка.
 */
export const CadRiserDetails: FC<IProps> = ({ title, draft, problems, disabled, onChange }) => {
  const id = useId();
  const [open, setOpen] = useState(() => hasDetails(draft));
  const failed = problems?.floors !== undefined || problems?.ei !== undefined;
  return (
    <details
      className="col-span-2 min-w-0"
      open={open || failed}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary className="flex min-h-[44px] cursor-pointer items-center text-sm font-medium">
        Подробнее
      </summary>
      <div className="grid min-w-0 grid-cols-2 gap-[var(--s-3)]">
        <label className={LABEL}>
          Этаж от
          <ClearableInput
            label={`Этаж от, ${title}`}
            value={draft.floorFrom}
            inputMode="numeric"
            maxLength={4}
            autoComplete="off"
            disabled={disabled}
            wrapperClassName="w-full"
            aria-invalid={problems?.floors !== undefined}
            onChange={(event) => onChange({ floorFrom: event.target.value })}
            onClear={() => onChange({ floorFrom: '' })}
          />
        </label>
        <label className={LABEL}>
          Этаж до
          <ClearableInput
            label={`Этаж до, ${title}`}
            value={draft.floorTo}
            inputMode="numeric"
            maxLength={4}
            autoComplete="off"
            disabled={disabled}
            wrapperClassName="w-full"
            aria-invalid={problems?.floors !== undefined}
            onChange={(event) => onChange({ floorTo: event.target.value })}
            onClear={() => onChange({ floorTo: '' })}
          />
        </label>
        <span className="col-span-2 empty:hidden">
          <Problem text={problems?.floors} />
        </span>

        <label className={`${LABEL} col-span-2`} htmlFor={`${id}-serves`}>
          Обслуживает
          <select
            id={`${id}-serves`}
            value={draft.serves}
            disabled={disabled}
            className={SELECT}
            onChange={(event) => onChange({ serves: event.target.value as RiserServes | '' })}
          >
            <option value="">—</option>
            {RISER_SERVES.map((serves) => (
              <option key={serves} value={serves}>
                {RISER_SERVES_LABELS[serves]}
              </option>
            ))}
          </select>
        </label>

        <label className={LABEL} htmlFor={`${id}-valve`}>
          Клапан
          <select
            id={`${id}-valve`}
            value={draft.valve}
            disabled={disabled}
            className={SELECT}
            onChange={(event) => onChange({ valve: event.target.value as RiserValve | '' })}
          >
            <option value="">—</option>
            {RISER_VALVES.map((valve) => (
              <option key={valve} value={valve}>
                {RISER_VALVE_LABELS[valve]}
              </option>
            ))}
          </select>
        </label>

        <label className={LABEL}>
          Предел EI
          <ClearableInput
            label={`Предел EI, ${title}`}
            value={draft.ei}
            maxLength={16}
            autoComplete="off"
            placeholder="EI60"
            disabled={disabled}
            wrapperClassName="w-full"
            aria-invalid={problems?.ei !== undefined}
            onChange={(event) => onChange({ ei: event.target.value })}
            onClear={() => onChange({ ei: '' })}
          />
          <Problem text={problems?.ei} />
        </label>
      </div>
    </details>
  );
};
