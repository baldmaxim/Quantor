'use client';

import type { FlagStateRead } from '@quantor/api-client';
import { Button, ErrorState, SkeletonRows, StatusBadge } from '@quantor/ui';

import { Section } from '@/components/common/Section';
import { useFeatureFlags, useResetFlag, useSession, useSetFlag } from '@/lib/queries';
import { sourceLabel, sourceTone } from '@/lib/status';

/**
 * Флаги возможностей.
 *
 * Главное, что видно на этой странице: включить незавершённую возможность нельзя.
 * Право у администратора есть, готовности у продукта — нет, и кнопка отключена не
 * из осторожности, а потому что включение флага не создаёт функциональность.
 *
 * Пилотная возможность (ADR-0023) — сделана, но выключена по умолчанию — включается на
 * пространство: у неё отдельные кнопки для текущего пространства администратора.
 *
 * У каждого значения показано, откуда оно и почему: «выключено» без причины через
 * месяц превращается в вопрос, на который никто не помнит ответа.
 */

/** Пилот: готов, выключен по умолчанию и переопределяется на уровне пространства. */
const isPilot = (flag: FlagStateRead): boolean =>
  flag.admin_editable && flag.workspace_scoped && !flag.follows_configuration && !flag.default;

interface IRowProps {
  flag: FlagStateRead;
  /** Имя текущего пространства или `null`, если администратор работает вне пространства. */
  workspaceName: string | null;
  hasWorkspace: boolean;
}

const Row = ({ flag, workspaceName, hasWorkspace }: IRowProps) => {
  const save = useSetFlag();
  const reset = useResetFlag();
  const busy = save.isPending || reset.isPending;

  const locked = !flag.admin_editable || flag.follows_configuration;
  const overridden = flag.source === 'system' || flag.source === 'workspace';
  const pilot = isPilot(flag);
  const workspaceLabel = workspaceName ? `«${workspaceName}»` : 'текущем';

  const lockReason = !flag.admin_editable
    ? 'возможность не готова: включается кодом'
    : flag.follows_configuration
      ? 'включается наличием ключа доступа, а не флагом'
      : null;

  return (
    <tr>
      <td>
        <div className="flex flex-col gap-[var(--s-2)]">
          <span className="font-medium">{flag.title}</span>
          <span className="mono text-micro text-muted">{flag.key}</span>
          <span className="max-w-[46ch] text-xs text-muted">{flag.description}</span>
        </div>
      </td>

      <td>
        <StatusBadge tone={flag.effective ? 'success' : 'neutral'}>
          {flag.effective ? 'включено' : 'выключено'}
        </StatusBadge>
      </td>

      <td className="text-xs text-muted">{flag.default ? 'включено' : 'выключено'}</td>

      <td>
        <div className="flex flex-col gap-[var(--s-2)]">
          <StatusBadge tone={sourceTone(flag.source)}>{sourceLabel(flag.source)}</StatusBadge>
          <span className="max-w-[32ch] text-micro text-muted">{flag.reason}</span>
        </div>
      </td>

      <td>
        <StatusBadge tone={flag.admin_editable ? 'success' : 'warning'}>{flag.stage}</StatusBadge>
      </td>

      <td>
        <div className="flex flex-wrap gap-[var(--s-3)]">
          <Button
            compact
            variant={flag.effective ? 'default' : 'primary'}
            disabled={locked || busy}
            title={lockReason ?? undefined}
            onClick={() =>
              save.mutate({
                key: flag.key,
                scope: 'system',
                enabled: !flag.effective,
                reason: flag.effective ? 'выключено администратором' : 'включено администратором',
              })
            }
          >
            {flag.effective ? 'Выключить' : 'Включить'}
          </Button>
          <Button
            compact
            disabled={!overridden || busy}
            onClick={() => reset.mutate({ key: flag.key, scope: 'system' })}
          >
            Сбросить
          </Button>
        </div>
        {pilot && (
          <div className="mt-[var(--s-3)] flex flex-col gap-[var(--s-2)]">
            <span className="text-micro text-muted">В пространстве {workspaceLabel}:</span>
            <div className="flex flex-wrap gap-[var(--s-3)]">
              <Button
                compact
                variant={flag.effective ? 'default' : 'primary'}
                disabled={!hasWorkspace || busy}
                title={hasWorkspace ? undefined : 'нет текущего пространства'}
                onClick={() =>
                  save.mutate({
                    key: flag.key,
                    scope: 'workspace',
                    enabled: !flag.effective,
                    reason: flag.effective
                      ? 'пилот выключен для пространства'
                      : 'пилот включён для пространства',
                  })
                }
              >
                {flag.effective ? 'Выключить в пространстве' : 'Включить в пространстве'}
              </Button>
              <Button
                compact
                disabled={flag.source !== 'workspace' || busy}
                onClick={() => reset.mutate({ key: flag.key, scope: 'workspace' })}
              >
                Сбросить для пространства
              </Button>
            </div>
          </div>
        )}
        {lockReason && <p className="mt-[var(--s-2)] text-micro text-muted">{lockReason}</p>}
        {save.isError && (
          <p className="mt-[var(--s-2)] text-xs text-danger">Сервер отклонил изменение.</p>
        )}
      </td>
    </tr>
  );
};

const Page = () => {
  const flags = useFeatureFlags();
  const session = useSession();
  // Переопределение на пространство сервер пишет в текущее пространство запроса, поэтому
  // и подпись берётся из сеанса, а не выбирается на странице.
  const workspaceId = session.data?.workspace_id ?? null;
  const workspaceName =
    session.data?.workspaces?.find((workspace) => workspace.id === workspaceId)?.name ?? null;

  if (flags.isPending) return <SkeletonRows rows={6} />;
  if (flags.isError) {
    return (
      <ErrorState
        title="Флаги не загрузились"
        onRetry={() => void flags.refetch()}
        description="Проверьте, что API отвечает."
      />
    );
  }

  return (
    <Section
      title="Флаги возможностей"
      description="Флаг показывает возможность, а не создаёт её. Незавершённое включается кодом после проверки готовности, а не отсюда. Пилотные возможности включаются на пространство."
    >
      <div className="table-scroll rounded-[var(--radius-md)] border border-border bg-surface">
        <table className="admin-table">
          <thead>
            <tr>
              <th>Возможность</th>
              <th>Сейчас</th>
              <th>По умолчанию</th>
              <th>Откуда и почему</th>
              <th>Готовность</th>
              <th>Действия</th>
            </tr>
          </thead>
          <tbody>
            {flags.data.map((flag) => (
              <Row
                key={flag.key}
                flag={flag}
                workspaceName={workspaceName}
                hasWorkspace={workspaceId !== null}
              />
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  );
};

export default Page;
