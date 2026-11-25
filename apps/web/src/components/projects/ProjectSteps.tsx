'use client';

import Link from 'next/link';
import type { FC } from 'react';

import { ButtonLink, cx } from '@/components/ui';
import {
  nextProjectStep,
  projectExtraLinks,
  projectSteps,
  type ProjectStepKey,
} from '@/lib/project-steps';
import { useFeatures } from '@/lib/queries';

/**
 * Полоса «Путь проекта» под шапкой карточки проекта: шаги по порядку с номером, справа - разделы
 * вне основного пути. Заменяет ряд из восьми кнопок в шапке. Что сделать на шаге - во всплывающей
 * подсказке, без лишнего текста на экране. Узкий экран - перенос строк, а не прокрутка вбок.
 */

export interface IProjectStepsProps {
  readonly projectId: string;
  /** Шаги, которые выполняются на этой странице (отмечаются «здесь»). */
  readonly current?: readonly ProjectStepKey[];
}

export const ProjectSteps: FC<IProjectStepsProps> = ({ projectId, current = [] }) => {
  const features = useFeatures();
  const steps = projectSteps(projectId, features);
  const extras = projectExtraLinks(projectId, features);

  return (
    <nav
      aria-label="Путь проекта"
      className="flex flex-none flex-wrap items-center gap-x-[var(--s-6)] gap-y-[var(--s-2)] border-b border-border bg-surface px-[var(--s-5)] py-[var(--s-2)] md:px-[var(--s-6)]"
    >
      <ol className="m-0 flex list-none flex-wrap items-center gap-[var(--s-1)] p-0">
        {steps.map((step, index) => {
          const here = current.includes(step.key);
          return (
            <li key={step.key} className="flex items-center gap-[var(--s-1)]">
              {index > 0 && (
                <span aria-hidden="true" className="text-xs text-muted opacity-50">
                  ›
                </span>
              )}
              <Link
                href={step.href}
                title={step.hint}
                aria-current={here ? 'step' : undefined}
                className={cx(
                  'flex min-h-[32px] items-center gap-[var(--s-3)] rounded-full px-[var(--s-4)] text-sm whitespace-nowrap transition-colors motion-reduce:transition-none max-md:min-h-[44px]',
                  here
                    ? 'bg-accent-soft font-medium text-accent'
                    : 'text-text hover:bg-surface-muted',
                )}
              >
                <span
                  aria-hidden="true"
                  className={cx(
                    'flex size-[18px] flex-none items-center justify-center rounded-full text-micro font-semibold',
                    here ? 'bg-accent text-surface' : 'bg-surface-muted text-muted',
                  )}
                >
                  {index + 1}
                </span>
                {step.title}
              </Link>
            </li>
          );
        })}
      </ol>
      {extras.length > 0 && (
        <p className="m-0 ml-auto flex flex-wrap items-center gap-x-[var(--s-5)] text-xs">
          {extras.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="text-muted underline-offset-4 hover:text-text hover:underline"
            >
              {link.label}
            </Link>
          ))}
        </p>
      )}
    </nav>
  );
};

export interface IProjectNextStepProps {
  readonly projectId: string;
  readonly current: ProjectStepKey;
}

/**
 * Кнопка в шапке страницы шага: «Дальше: <шаг>» с подсказкой, что там сделать. Следующего
 * шага нет (последний или раздел закрыт флагом) - ничего.
 */
export const ProjectNextStep: FC<IProjectNextStepProps> = ({ projectId, current }) => {
  const next = nextProjectStep(projectSteps(projectId, useFeatures()), current);
  if (next === null) return null;
  return (
    <ButtonLink
      href={next.href}
      title={`Следующий шаг: ${next.hint}`}
      transitionTypes={['nav-forward']}
    >
      Дальше: {next.title} →
    </ButtonLink>
  );
};
