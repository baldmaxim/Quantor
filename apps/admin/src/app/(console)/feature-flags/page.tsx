'use client';

import type { FlagStateRead } from '@quantor/api-client';
import { Button, ErrorState, SkeletonRows, StatusBadge } from '@quantor/ui';

import { Section } from '@/components/common/Section';
import { useFeatureFlags, useResetFlag, useSetFlag } from '@/lib/queries';
import { sourceLabel, sourceTone } from '@/lib/status';

/**
 * Флаги возможностей.
 *
 * Главное, что видно на этой странице: включить незавершённую возможность нельзя.
 * Право у администратора есть, готовности у продукта — нет, и кнопка отключена не
 * из осторожности, а потому что включение флага не создаёт функциональность.
 *
 * У каждого значения показано, откуда оно и почему: «выключено» без причины через
 * месяц превращается в вопрос, на который никто не помнит ответа.
 */

const Row = ({ flag }: { flag: FlagStateRead }) => {
  const save = useSetFlag();
  const reset = useResetFlag();
  const busy = save.isPending || reset.isPending;

  const locked = !flag.admin_editable || flag.follows_configuration;
  const overridden = flag.source === 'system' || flag.source === 'workspace';

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
      description="Флаг показывает возможность, а не создаёт её. Незавершённое включается кодом после проверки готовности, а не отсюда."
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
              <Row key={flag.key} flag={flag} />
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  );
};

export default Page;
