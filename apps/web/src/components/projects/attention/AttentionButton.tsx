'use client';

import type { FC } from 'react';

import { Button } from '@/components/ui';

/** Кнопка шапки проекта «Вопросы: N»: открывает окно прямых вопросов. Нет вопросов - не видна. */
export const AttentionButton: FC<{ readonly count: number; readonly onClick: () => void }> = ({
  count,
  onClick,
}) => (count > 0 ? <Button onClick={onClick}>Вопросы: {count}</Button> : null);
