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
 * Полоса «Путь проекта» под шапкой карточки проекта: шаги по порядку с номером и одной строкой
 * «что сделать», ниже - разделы вне основного пути. Заменяет ряд из восьми кнопок в шапке.
 * На узком экране полоса листается вбок, страница - нет.
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
      className="flex-none border-b border-border bg-surface px-[var(--s-5)] md:px-[var(--s-6)]"
    >
      <ol className="m-0 flex list-none gap-[var(--s-2)] overflow-x-auto p-0 py-[var(--s-3)] [overscroll-behavior-x:contain]">
        {steps.map((step, index) => {
          const here = current.includes(step.key);
          return (
            <li key={step.key} className="flex flex-none items-center gap-[var(--s-2)]">
              {index > 0 && (
                <span aria-hidden="true" className="text-muted opacity-60">
                  →
                </span>
              )}
              <Link
                href={step.href}
                aria-current={here ? 'step' : undefined}
                className={cx(
                  'flex min-h-[44px] items-center gap-[var(--s-3)] rounded-[var(--radius-sm)] border px-[var(--s-4)] py-[var(--s-2)] transition-colors motion-reduce:transition-none',
                  here
                    ? 'border-accent bg-accent-soft'
                    : 'border-transparent hover:bg-surface-muted',
                )}
              >
                <span
                  aria-hidden="true"
                  className={cx(
                    'flex size-[20px] flex-none items-center justify-center rounded-full border text-micro font-semibold',
                    here ? 'border-accent text-accent' : 'border-border-strong text-muted',
                  )}
                >
                  {index + 1}
                </span>
                <span className="flex flex-col leading-tight">
                  <span className="text-sm font-medium whitespace-nowrap">{step.title}</span>
                  <span className="text-xs whitespace-nowrap text-muted">{step.hint}</span>
                </span>
              </Link>
            </li>
          );
        })}
      </ol>
      {extras.length > 0 && (
        <p className="m-0 flex flex-wrap items-center gap-x-[var(--s-5)] gap-y-[var(--s-1)] pb-[var(--s-3)] text-xs text-muted">
          <span>Ещё:</span>
          {extras.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="text-accent underline-offset-4 hover:underline"
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
