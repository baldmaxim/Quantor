'use client';

import { Button, ErrorState, SkeletonRows, StatusBadge } from '@quantor/ui';

import { Section } from '@/components/common/Section';
import { useDiagnostics } from '@/lib/queries';
import { statusView, type ProbeStatus } from '@/lib/status';

/**
 * Состояние установки.
 *
 * Обновление — по кнопке. Автоматический опрос добавляет нагрузку ровно тогда, когда
 * система нездорова, а сюда приходят именно в этот момент.
 *
 * Рядом с состоянием всегда видно, откуда оно известно и когда проверялось: «в порядке»
 * без ответа на эти вопросы — половина сведений.
 */

const SOURCE_LABEL: Record<string, string> = {
  live: 'проверено сейчас',
  reported: 'сообщено процессом',
  config: 'из настроек',
  unknown: 'не успело ответить',
};

const Page = () => {
  const diagnostics = useDiagnostics();

  if (diagnostics.isPending) return <SkeletonRows rows={6} />;
  if (diagnostics.isError) {
    return (
      <ErrorState
        title="Диагностика не загрузилась"
        onRetry={() => void diagnostics.refetch()}
        description="Проверьте, что API отвечает."
      />
    );
  }

  const overall = statusView(diagnostics.data.status as ProbeStatus);

  return (
    <Section
      title="Состояние системы"
      description="Что работает, что нет и что с этим делать. Проверка выполняется по запросу — страница не опрашивает зависимости сама."
      actions={
        <Button
          variant="primary"
          disabled={diagnostics.isFetching}
          onClick={() => void diagnostics.refetch()}
        >
          {diagnostics.isFetching ? 'Проверяем…' : 'Проверить снова'}
        </Button>
      }
    >
      <div className="flex flex-wrap items-center gap-[var(--s-4)] rounded-[var(--radius-md)] border border-border bg-surface p-[var(--s-5)]">
        <StatusBadge tone={overall.tone}>{overall.label}</StatusBadge>
        <span className="text-xs text-muted">
          итог по обязательным компонентам · проверено{' '}
          {new Date(diagnostics.data.generated_at).toLocaleString('ru-RU')}
        </span>
      </div>

      <div className="flex flex-col gap-[var(--s-3)]">
        {diagnostics.data.components.map((component) => {
          const view = statusView(component.status as ProbeStatus);
          const facts = Object.entries(component.facts ?? {});

          return (
            <div
              key={component.name}
              className="flex flex-col gap-[var(--s-3)] rounded-[var(--radius-md)] border border-border bg-surface p-[var(--s-5)]"
            >
              <div className="flex flex-wrap items-center gap-[var(--s-4)]">
                <span className="text-sm font-medium">{component.title}</span>
                <StatusBadge tone={view.tone}>{view.label}</StatusBadge>
                <span className="text-micro text-muted">
                  {SOURCE_LABEL[component.source] ?? component.source}
                  {component.duration_ms !== null && component.duration_ms !== undefined
                    ? ` · ${component.duration_ms} мс`
                    : ''}
                </span>
              </div>

              {component.detail && (
                <p className="max-w-[70ch] text-sm text-muted">{component.detail}</p>
              )}

              {component.remediation && (
                <p className="max-w-[70ch] text-sm">
                  <span className="text-muted">Что сделать: </span>
                  {component.remediation}
                </p>
              )}

              {facts.length > 0 && (
                <dl className="flex flex-wrap gap-x-[var(--s-6)] gap-y-[var(--s-2)]">
                  {facts.map(([key, value]) => (
                    <div key={key} className="flex gap-[var(--s-3)]">
                      <dt className="text-micro text-muted">{key}</dt>
                      <dd className="mono m-0 text-micro wrap-anywhere">{value}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </div>
          );
        })}
      </div>
    </Section>
  );
};

export default Page;
