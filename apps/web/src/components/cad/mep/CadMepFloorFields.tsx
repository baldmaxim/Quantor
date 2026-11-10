'use client';

import type { FC } from 'react';

import { ClearableInput } from '@/components/ui/ClearableInput';

interface ICadMepFloorFieldsProps {
  elevation: string;
  height: string;
  onElevation: (value: string) => void;
  onHeight: (value: string) => void;
  /** Ошибки показываются после первой попытки отправки. */
  elevationProblem: string | null;
  heightProblem: string | null;
  showProblems: boolean;
}

const LABEL = 'flex min-w-0 flex-col gap-[var(--s-2)] text-sm';

/** Два поля ручного ввода: отметка пола и высота этажа, мм. Пустое поле - «по документации». */
export const CadMepFloorFields: FC<ICadMepFloorFieldsProps> = ({
  elevation,
  height,
  onElevation,
  onHeight,
  elevationProblem,
  heightProblem,
  showProblems,
}) => (
  <>
    <label className={LABEL}>
      <span>Отметка пола, мм</span>
      <ClearableInput
        label="Отметка пола, мм"
        inputMode="numeric"
        autoComplete="off"
        placeholder="пусто — по документации"
        value={elevation}
        onChange={(event) => onElevation(event.target.value)}
        onClear={() => onElevation('')}
        aria-invalid={showProblems && elevationProblem !== null}
      />
      {showProblems && elevationProblem && (
        <span role="alert" className="text-xs text-danger">
          {elevationProblem}
        </span>
      )}
    </label>
    <label className={LABEL}>
      <span>Высота этажа, мм</span>
      <ClearableInput
        label="Высота этажа, мм"
        inputMode="numeric"
        autoComplete="off"
        placeholder="пусто — по документации"
        value={height}
        onChange={(event) => onHeight(event.target.value)}
        onClear={() => onHeight('')}
        aria-invalid={showProblems && heightProblem !== null}
      />
      {showProblems && heightProblem && (
        <span role="alert" className="text-xs text-danger">
          {heightProblem}
        </span>
      )}
    </label>
  </>
);
