'use client';

import { useId, type FC } from 'react';

import { ClearableInput } from '@/components/ui/ClearableInput';
import type { ChannelShape, IRiserDraft, IRiserProblems } from '@/lib/cad/risers';

import { LABEL, Problem, SELECT } from './riser-ui';

interface IProps {
  readonly title: string;
  readonly draft: IRiserDraft;
  readonly problems: IRiserProblems | null;
  readonly disabled: boolean;
  readonly onChange: (patch: Partial<IRiserDraft>) => void;
}

/**
 * Размер канала воздушной системы: прямоугольное «Сечение» (два числа a×b) или «Ø канала».
 * Переключение формы очищает размеры другой формы: в запись уходит только одна.
 */
export const CadRiserChannel: FC<IProps> = ({ title, draft, problems, disabled, onChange }) => {
  const id = useId();
  const round = draft.channelShape === 'round';
  return (
    <div className="col-span-2 flex min-w-0 flex-col gap-[var(--s-3)]">
      <label className={LABEL} htmlFor={`${id}-shape`}>
        Канал
        <select
          id={`${id}-shape`}
          value={draft.channelShape}
          disabled={disabled}
          className={SELECT}
          onChange={(event) =>
            onChange({
              channelShape: event.target.value as ChannelShape,
              sectionA: '',
              sectionB: '',
              channelD: '',
            })
          }
        >
          <option value="section">Сечение a×b</option>
          <option value="round">Круглый, Ø</option>
        </select>
      </label>
      {round ? (
        <label className={LABEL}>
          Ø канала, мм
          <ClearableInput
            label={`Ø канала, мм, ${title}`}
            value={draft.channelD}
            inputMode="numeric"
            maxLength={4}
            autoComplete="off"
            disabled={disabled}
            wrapperClassName="w-full"
            aria-invalid={problems?.channelD !== undefined}
            onChange={(event) => onChange({ channelD: event.target.value })}
            onClear={() => onChange({ channelD: '' })}
          />
          <Problem text={problems?.channelD} />
        </label>
      ) : (
        <div className="grid min-w-0 grid-cols-2 gap-[var(--s-3)]">
          <label className={LABEL}>
            Сечение: a, мм
            <ClearableInput
              label={`Сечение a, мм, ${title}`}
              value={draft.sectionA}
              inputMode="numeric"
              maxLength={4}
              autoComplete="off"
              disabled={disabled}
              wrapperClassName="w-full"
              aria-invalid={problems?.section !== undefined}
              onChange={(event) => onChange({ sectionA: event.target.value })}
              onClear={() => onChange({ sectionA: '' })}
            />
          </label>
          <label className={LABEL}>
            Сечение: b, мм
            <ClearableInput
              label={`Сечение b, мм, ${title}`}
              value={draft.sectionB}
              inputMode="numeric"
              maxLength={4}
              autoComplete="off"
              disabled={disabled}
              wrapperClassName="w-full"
              aria-invalid={problems?.section !== undefined}
              onChange={(event) => onChange({ sectionB: event.target.value })}
              onClear={() => onChange({ sectionB: '' })}
            />
          </label>
          <span className="col-span-2 empty:hidden">
            <Problem text={problems?.section} />
          </span>
        </div>
      )}
      {/* Ø трубы воздушной системы не задаётся: значение из старых данных показываем ошибкой. */}
      <Problem text={problems?.dn} />
    </div>
  );
};
