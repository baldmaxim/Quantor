'use client';

import { readiness } from '@quantor/api-client';
import { ErrorState, SkeletonRows } from '@quantor/ui';
import { useQuery } from '@tanstack/react-query';

import { Section } from '@/components/common/Section';
import { Tile } from '@/components/common/Tile';
import { env } from '@/lib/env';
import { useFeatureFlags, useMeta, useTenderHubStatus } from '@/lib/queries';
import { NOT_MEASURED, statusView, type ProbeStatus } from '@/lib/status';

/**
 * Обзор состояния установки.
 *
 * Показывается только то, что подтверждено сервером. Метрики, которых ещё нет —
 * пульс воркера, счётчик отказавших заданий, — обозначены прочерком, а не нулём:
 * ноль здесь читается как «всё хорошо», и это была бы неправда.
 */

const COMPONENT_STATUS: Record<string, ProbeStatus> = {
  ok: 'healthy',
  outdated: 'degraded',
  unavailable: 'unavailable',
};

const Page = () => {
  const meta = useMeta();
  const flags = useFeatureFlags();
  const tenderhub = useTenderHubStatus();

  // Готовность публична и отвечает без прав: это проба для балансировщика.
  const health = useQuery({
    queryKey: ['readiness'],
    queryFn: async () => (await readiness({ throwOnError: false })).data ?? null,
    retry: false,
  });

  const components = health.data?.components ?? [];
  const componentOf = (name: string) => components.find((item) => item.name === name);
  const enabledFlags = flags.data?.filter((flag) => flag.effective).length;

  return (
    <Section
      title="Обзор"
      description="Состояние установки по подтверждённым данным сервера. Метрики, которых ещё нет, показаны прочерком."
    >
      {meta.isError && (
        <ErrorState
          title="API не отвечает"
          description="Версии и состояние получить не удалось. Остальные плитки показывают последнее известное."
          onRetry={() => void meta.refetch()}
        />
      )}

      {meta.isPending ? (
        <SkeletonRows rows={4} />
      ) : (
        <div className="grid gap-[var(--s-4)] sm:grid-cols-2 xl:grid-cols-3">
          <Tile
            label="Сборка админки"
            value={env.buildVersion}
            hint="Задаётся при сборке этого приложения"
          />
          <Tile
            label="API"
            value={
              meta.data
                ? `${meta.data.api_version} · схема ${meta.data.schema_version}`
                : NOT_MEASURED
            }
            hint={meta.data?.environment}
          />
          <Tile
            label="Вход"
            value={meta.data?.auth_mode === 'oidc' ? 'провайдер OIDC' : 'режим разработки'}
            tone={meta.data?.auth_mode === 'oidc' ? 'success' : 'warning'}
            badge={meta.data?.auth_mode === 'oidc' ? 'настроен' : 'без проверки'}
            hint={
              meta.data?.auth_mode === 'dev'
                ? 'Допустим только локально: вне local запуск не пройдёт'
                : undefined
            }
          />

          {(['database', 'database_schema', 'object_storage'] as const).map((name) => {
            const component = componentOf(name);
            const status: ProbeStatus = component
              ? (COMPONENT_STATUS[component.status] ?? 'unknown')
              : 'unknown';
            const view = statusView(status);
            const labels: Record<string, string> = {
              database: 'PostgreSQL',
              database_schema: 'Схема базы',
              object_storage: 'Объектное хранилище',
            };
            return (
              <Tile
                key={name}
                label={labels[name] ?? name}
                value={
                  name === 'database_schema'
                    ? (health.data?.schema_revision ?? NOT_MEASURED)
                    : view.label
                }
                tone={view.tone}
                badge={view.label}
                hint={component?.detail ?? undefined}
              />
            );
          })}

          <Tile
            label="TenderHUB"
            value={tenderhub.data?.configured ? 'настроен' : 'не настроен'}
            tone={tenderhub.data?.configured ? 'success' : 'neutral'}
            badge={
              tenderhub.data
                ? `связанных проектов: ${tenderhub.data.linked_project_count}`
                : undefined
            }
            hint="Связь проверяется явно, на странице интеграций"
          />
          <Tile
            label="Включённых возможностей"
            value={
              enabledFlags === undefined
                ? NOT_MEASURED
                : `${enabledFlags} из ${flags.data?.length ?? 0}`
            }
            hint="Флаг показывает только то, что действительно работает"
          />
          <Tile
            label="Воркер заданий"
            value={NOT_MEASURED}
            badge="не измеряется"
            hint="Пульс исполнителя появится вместе с выносом заданий в отдельный процесс"
          />
          <Tile
            label="Отказавшие задания"
            value={NOT_MEASURED}
            badge="не измеряется"
            hint="Ноль здесь читался бы как «всё хорошо», а это пока неизвестно"
          />
        </div>
      )}
    </Section>
  );
};

export default Page;
