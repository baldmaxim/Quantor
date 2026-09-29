'use client';

import type { CalcDiscipline, CalcFactTypeRead } from '@quantor/api-client';
import { useId, useState } from 'react';

import { Button, Dialog, DialogActions, ErrorState } from '@/components/ui';
import { useAddManualFact } from '@/lib/calc/fact-actions';
import { unitTitle } from '@/lib/calc/format';
import {
  SUBJECT_TITLES,
  buildSubject,
  buildValue,
  needsSystem,
  subjectFields,
  type ISubjectInput,
  type IValueInput,
} from '@/lib/calc/manual';
import { errorMessage, extractCode, extractMessage } from '@/lib/errors';

/**
 * Ручной ввод значения — последний путь после документов и вывода (ADR-0030).
 *
 * Значение записывается утверждением источника «Ручной ввод» с основанием: оно видно в
 * цепочке объяснения. Если документ говорит другое, реестр откроет конфликт — ручное значение
 * не перекрывает документ молча.
 *
 * Допущение (значение не по документу, с альтернативами) предлагается только там, где политика
 * требования его разрешает; иначе — только значение по документу.
 */

const FIELD =
  'h-[var(--h-ctl)] max-md:h-[44px] rounded-[var(--radius-sm)] border border-border-control bg-surface px-[var(--s-4)] text-base text-text md:text-sm';

export interface IManualTarget {
  type: CalcFactTypeRead;
  title: string;
  discipline: CalcDiscipline | null;
  systemCode: string | null;
  /** Политика требования разрешает допущение инженера (`assumption = MANUAL`). */
  assumptionAllowed?: boolean;
}

interface IManualFactDialogProps {
  projectId: string;
  target: IManualTarget | null;
  onClose: () => void;
}

export const ManualFactDialog = ({ projectId, target, onClose }: IManualFactDialogProps) => (
  <Dialog
    open={target !== null}
    onClose={onClose}
    title="Ввести значение вручную"
    description={target?.title}
    size="lg"
  >
    {target && (
      <ManualFactForm
        key={`${target.type.key}|${target.systemCode ?? ''}`}
        projectId={projectId}
        target={target}
        onClose={onClose}
      />
    )}
  </Dialog>
);

const ManualFactForm = ({
  projectId,
  target,
  onClose,
}: {
  projectId: string;
  target: IManualTarget;
  onClose: () => void;
}) => {
  const { type } = target;
  const baseId = useId();
  const [subject, setSubject] = useState<ISubjectInput>({
    building: '1',
    section: '',
    floor: '',
    room: '',
    qualifier: '',
    discipline: target.discipline,
    systemCode: target.systemCode ?? '',
  });
  const [value, setValue] = useState<IValueInput>({ number: '', low: '', high: '', choice: '' });
  const [note, setNote] = useState('');
  const [assumed, setAssumed] = useState(false);
  const [alternatives, setAlternatives] = useState('');
  const [problem, setProblem] = useState<string | null>(null);
  const mutation = useAddManualFact(projectId);
  const unit = type.unit_title ?? unitTitle(type.unit);

  const submit = () => {
    const builtSubject = buildSubject(type, subject);
    const builtValue = buildValue(type, value);
    if (typeof builtSubject === 'string') return setProblem(builtSubject);
    if (typeof builtValue === 'string') return setProblem(builtValue);
    if (note.trim().length < 3) return setProblem('Укажите основание: документ, лист или решение');
    const options = alternatives
      .split(';')
      .map((item) => item.trim())
      .filter(Boolean);
    if (assumed && !options.length) {
      return setProblem('У допущения должны быть альтернативы: чем ещё может оказаться значение');
    }
    setProblem(null);
    mutation.mutate(
      {
        factType: type.key,
        subject: builtSubject,
        value: builtValue,
        note: note.trim(),
        alternatives: assumed ? options : undefined,
      },
      { onSuccess: onClose },
    );
  };

  return (
    <div className="flex flex-col gap-[var(--s-4)]">
      <p className="text-sm text-muted">{type.description}</p>
      {subjectFields(type).map(({ field, required }) => (
        <label
          key={field}
          htmlFor={`${baseId}-${field}`}
          className="flex flex-col gap-[var(--s-2)]"
        >
          <span className="text-sm">
            {SUBJECT_TITLES[field]}
            {!required && <span className="text-muted"> — необязательно</span>}
          </span>
          {field === 'qualifier' ? (
            <select
              id={`${baseId}-${field}`}
              value={subject.qualifier}
              onChange={(event) => setSubject({ ...subject, qualifier: event.target.value })}
              className={FIELD}
            >
              <option value="">— выберите —</option>
              {type.qualifier_options.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.title}
                </option>
              ))}
            </select>
          ) : (
            <input
              id={`${baseId}-${field}`}
              value={subject[field]}
              maxLength={64}
              placeholder={field === 'floor' ? '12, −1 или 2..24' : undefined}
              onChange={(event) => setSubject({ ...subject, [field]: event.target.value })}
              className={FIELD}
            />
          )}
        </label>
      ))}
      {needsSystem(type) && (
        <p className="text-sm">
          Система: <span className="font-medium">{subject.systemCode || 'не выбрана'}</span>
        </p>
      )}
      <ValueEditor type={type} unit={unit} value={value} onChange={setValue} baseId={baseId} />
      <label htmlFor={`${baseId}-note`} className="flex flex-col gap-[var(--s-2)]">
        <span className="text-sm">Основание</span>
        <textarea
          id={`${baseId}-note`}
          value={note}
          maxLength={1000}
          rows={2}
          placeholder="Например: разрез 1-1, лист АР-15; решение инженера ВК"
          onChange={(event) => setNote(event.target.value)}
          className="rounded-[var(--radius-sm)] border border-border-control bg-surface px-[var(--s-4)] py-[var(--s-2)] text-base text-text md:text-sm"
        />
      </label>
      {target.assumptionAllowed && (
        <label className="flex min-h-[44px] items-center gap-[var(--s-3)] text-sm">
          <input
            type="checkbox"
            checked={assumed}
            onChange={(event) => setAssumed(event.target.checked)}
            className="size-5"
          />
          Это допущение инженера, а не значение из документа
        </label>
      )}
      {assumed && (
        <label htmlFor={`${baseId}-alternatives`} className="flex flex-col gap-[var(--s-2)]">
          <span className="text-sm">Альтернативы — через «;»</span>
          <input
            id={`${baseId}-alternatives`}
            value={alternatives}
            maxLength={1000}
            placeholder="Например: 3,0 м; 3,3 м"
            onChange={(event) => setAlternatives(event.target.value)}
            className={FIELD}
          />
        </label>
      )}
      {problem && <p className="text-sm text-danger">{problem}</p>}
      {mutation.isError && (
        <ErrorState
          title="Значение не записано"
          code={extractCode(mutation.error)}
          description={errorMessage(extractCode(mutation.error), extractMessage(mutation.error))}
        />
      )}
      <DialogActions>
        <Button onClick={onClose} disabled={mutation.isPending}>
          Отмена
        </Button>
        <Button
          variant="primary"
          onClick={submit}
          disabled={mutation.isPending}
          loading={mutation.isPending}
          loadingLabel="Записываем…"
        >
          Записать
        </Button>
      </DialogActions>
    </div>
  );
};

const ValueEditor = ({
  type,
  unit,
  value,
  onChange,
  baseId,
}: {
  type: CalcFactTypeRead;
  unit: string;
  value: IValueInput;
  onChange: (value: IValueInput) => void;
  baseId: string;
}) => {
  const id = `${baseId}-value`;
  if (type.value_kind === 'ENUM' || type.value_kind === 'BOOLEAN') {
    const options =
      type.value_kind === 'ENUM'
        ? type.options
        : [
            { value: 'true', title: 'да' },
            { value: 'false', title: 'нет' },
          ];
    return (
      <label htmlFor={id} className="flex flex-col gap-[var(--s-2)]">
        <span className="text-sm">Значение</span>
        <select
          id={id}
          value={value.choice}
          onChange={(event) => onChange({ ...value, choice: event.target.value })}
          className={FIELD}
        >
          <option value="">— выберите —</option>
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.title}
            </option>
          ))}
        </select>
      </label>
    );
  }
  if (type.value_kind === 'RANGE') {
    return (
      <div className="flex flex-wrap gap-[var(--s-4)]">
        {(['low', 'high'] as const).map((bound) => (
          <label key={bound} htmlFor={`${id}-${bound}`} className="flex flex-col gap-[var(--s-2)]">
            <span className="text-sm">
              {bound === 'low' ? 'От' : 'До'}
              {unit && `, ${unit}`}
            </span>
            <input
              id={`${id}-${bound}`}
              inputMode="decimal"
              value={value[bound]}
              onChange={(event) => onChange({ ...value, [bound]: event.target.value })}
              className={FIELD}
            />
          </label>
        ))}
      </div>
    );
  }
  return (
    <label htmlFor={id} className="flex flex-col gap-[var(--s-2)]">
      <span className="text-sm">Значение{unit && `, ${unit}`}</span>
      <input
        id={id}
        inputMode={type.value_kind === 'TEXT' ? 'text' : 'decimal'}
        value={value.number}
        maxLength={type.value_kind === 'TEXT' ? 1000 : 40}
        onChange={(event) => onChange({ ...value, number: event.target.value })}
        className={FIELD}
      />
    </label>
  );
};
