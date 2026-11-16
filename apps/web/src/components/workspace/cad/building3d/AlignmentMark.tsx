'use client';

import { cx } from '@quantor/ui';
import type { FC } from 'react';

import type { AlignmentGrade, IAlignmentNote } from '@/lib/cad/building3d-geometry';

const DOT: Record<AlignmentGrade, string> = {
  green: 'bg-success',
  yellow: 'bg-warning',
  red: 'bg-danger',
};

/** Цвет светофора продублирован словами: его читают и без различения цветов, и с экрана. */
const GRADE_LABEL: Record<AlignmentGrade, string> = {
  green: 'совмещение точное',
  yellow: 'совмещение приблизительное',
  red: 'совмещение ненадёжное',
};

/** Пометка совмещения этажа в строке списка: светофор качества и короткий текст. */
export const AlignmentMark: FC<{ readonly note: IAlignmentNote }> = ({ note }) => (
  <span
    className={cx(
      'flex items-center gap-[var(--s-2)] text-xs',
      note.warn ? 'text-warning' : 'text-muted',
    )}
  >
    {note.grade !== null && (
      <span
        role="img"
        aria-label={GRADE_LABEL[note.grade]}
        title={GRADE_LABEL[note.grade]}
        className={cx('h-2 w-2 flex-none rounded-full', DOT[note.grade])}
      />
    )}
    <span className="min-w-0">{note.text}</span>
  </span>
);
