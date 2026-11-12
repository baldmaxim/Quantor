'use client';

import type { DocQuestionOut } from '@quantor/api-client';
import { useId, useState, type FC } from 'react';

import { Button } from '@/components/ui';
import { ClearableInput } from '@/components/ui/ClearableInput';
import {
  ROSETTE_OPTIONS,
  buildManualAnswer,
  emptyManualForm,
  manualLayout,
  notInProjectBody,
  type DocAnswerBody,
  type IManualForm,
  type Qualifier,
} from '@/lib/consistency/doc-questions';

/**
 * Ввод ответа человеком: «Ввести вручную» (размеры в мм целыми и обязательное пояснение
 * «откуда») и «Нет в проекте» (пояснение необязательно). Область — весь проект.
 */

interface IFormProps {
  readonly question: Pick<DocQuestionOut, 'code' | 'value_kind' | 'min_mm' | 'max_mm'>;
  readonly pending: boolean;
  /** `done` вызывается после успешной записи: форма закрывается. */
  readonly onSubmit: (body: DocAnswerBody, done: () => void) => void;
}

type Mode = 'closed' | 'manual' | 'absent';

const FIELD =
  'w-full rounded-[var(--radius-sm)] border border-border-control bg-surface px-[var(--s-4)] text-base text-text md:text-sm';
const SELECT = `${FIELD} h-[var(--h-ctl)] max-md:h-[44px]`;
const LABEL = 'flex min-w-0 flex-col gap-[var(--s-2)] text-xs text-muted';

export const DocAnswerForm: FC<IFormProps> = ({ question, pending, onSubmit }) => {
  const baseId = useId();
  const layout = manualLayout(question);
  const [mode, setMode] = useState<Mode>('closed');
  const [form, setForm] = useState<IManualForm>(() => emptyManualForm(layout));
  const [problem, setProblem] = useState<string | null>(null);

  const patch = (next: Partial<IManualForm>) => {
    setForm((current) => ({ ...current, ...next }));
    setProblem(null);
  };
  const setNumber = (index: number, value: string) =>
    patch({ numbers: form.numbers.map((item, at) => (at === index ? value : item)) });
  const close = () => {
    setMode('closed');
    setProblem(null);
  };

  const submitManual = () => {
    const result = buildManualAnswer(question, form);
    if ('error' in result) {
      setProblem(result.error);
      return;
    }
    onSubmit(result.body, close);
  };

  if (mode === 'closed') {
    return (
      <div className="flex flex-wrap gap-[var(--s-3)]">
        <Button onClick={() => setMode('manual')}>Ввести вручную</Button>
        <Button onClick={() => setMode('absent')}>Нет в проекте</Button>
      </div>
    );
  }

  const noteField = (required: boolean) => (
    <label className={LABEL}>
      {required ? 'Откуда значение' : 'Пояснение (необязательно)'}
      <ClearableInput
        label={required ? 'Откуда значение' : 'Пояснение'}
        value={form.note}
        maxLength={2000}
        placeholder={required ? 'Например: разрез 1-1, лист АР-15' : undefined}
        onChange={(event) => patch({ note: event.target.value })}
        onClear={() => patch({ note: '' })}
        wrapperClassName="w-full"
      />
    </label>
  );

  return (
    <div className="flex flex-col gap-[var(--s-4)] rounded-[var(--radius-sm)] border border-border bg-surface-muted px-[var(--s-4)] py-[var(--s-4)]">
      {mode === 'manual' ? (
        <>
          {layout.showText && (
            <label className={LABEL}>
              Значение
              <ClearableInput
                label="Значение"
                value={form.text}
                maxLength={500}
                onChange={(event) => patch({ text: event.target.value })}
                onClear={() => patch({ text: '' })}
                wrapperClassName="w-full"
              />
            </label>
          )}
          {layout.numberLabels.map((label, index) =>
            layout.showRound && form.round && index > 0 ? null : (
              <label key={label} className={LABEL}>
                {layout.showRound && form.round ? 'Диаметр, мм' : label}
                <ClearableInput
                  label={layout.showRound && form.round ? 'Диаметр, мм' : label}
                  inputMode="numeric"
                  value={form.numbers[index] ?? ''}
                  onChange={(event) => setNumber(index, event.target.value)}
                  onClear={() => setNumber(index, '')}
                  wrapperClassName="w-full"
                />
              </label>
            ),
          )}
          {layout.showRound && (
            <label className="flex min-h-[44px] items-center gap-[var(--s-3)] text-sm">
              <input
                type="checkbox"
                checked={form.round}
                onChange={(event) => patch({ round: event.target.checked })}
                className="size-5"
              />
              Круглое сечение (диаметр)
            </label>
          )}
          {layout.showQualifier && (
            <label className={LABEL} htmlFor={`${baseId}-qualifier`}>
              Оговорка
              <select
                id={`${baseId}-qualifier`}
                value={form.qualifier}
                onChange={(event) => patch({ qualifier: event.target.value as Qualifier })}
                className={SELECT}
              >
                <option value="">без оговорки</option>
                <option value="min">не менее</option>
                <option value="max">не более</option>
              </select>
            </label>
          )}
          {layout.showRosette && (
            <label className={LABEL} htmlFor={`${baseId}-rosette`}>
              Положение розетки
              <select
                id={`${baseId}-rosette`}
                value={form.rosette}
                onChange={(event) => patch({ rosette: event.target.value })}
                className={SELECT}
              >
                <option value="">— выберите —</option>
                {ROSETTE_OPTIONS.map((option) => (
                  <option key={option.code} value={option.code}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          )}
          {noteField(true)}
        </>
      ) : (
        noteField(false)
      )}
      {problem && (
        <p role="alert" className="text-sm text-danger">
          {problem}
        </p>
      )}
      <div className="flex flex-wrap gap-[var(--s-3)]">
        <Button
          variant="primary"
          loading={pending}
          onClick={() =>
            mode === 'manual' ? submitManual() : onSubmit(notInProjectBody(form.note), close)
          }
        >
          {mode === 'manual' ? 'Сохранить' : 'Подтвердить: нет в проекте'}
        </Button>
        <Button onClick={close} disabled={pending}>
          Отмена
        </Button>
      </div>
    </div>
  );
};
