'use client';

import { Button, ErrorState, SkeletonRows, StatusBadge } from '@quantor/ui';

import { Section } from '@/components/common/Section';
import { Tile } from '@/components/common/Tile';
import { useTenderHubStatus, useTestTenderHub } from '@/lib/queries';

/**
 * Интеграции: TenderHUB.
 *
 * Ключ доступа не показывается ни целиком, ни частями — только факт его наличия.
 * Показать даже несколько символов значит помочь тому, кто подбирает.
 *
 * Связь проверяется по кнопке, а не при открытии страницы. Иначе открытие зависело бы
 * от доступности чужой системы — а сюда приходят как раз тогда, когда она недоступна.
 */

const Page = () => {
  const status = useTenderHubStatus();
  const probe = useTestTenderHub();

  if (status.isPending) return <SkeletonRows rows={3} />;
  if (status.isError) {
    return (
      <ErrorState
        title="Состояние интеграции не загрузилось"
        onRetry={() => void status.refetch()}
        description="Проверьте, что API отвечает."
      />
    );
  }

  const configured = status.data.configured;

  return (
    <Section
      title="TenderHUB"
      description="Портал берёт из тендера только его удостоверение — номер, название и заказчика. Позиции ВОР и строки смет не читаются."
      actions={
        <Button
          variant="primary"
          disabled={!configured || probe.isPending}
          title={configured ? undefined : 'Нет ключа доступа: проверять нечего'}
          onClick={() => probe.mutate()}
        >
          {probe.isPending ? 'Проверяем…' : 'Проверить связь'}
        </Button>
      }
    >
      <div className="grid gap-[var(--s-4)] sm:grid-cols-2 xl:grid-cols-3">
        <Tile
          label="Интеграция"
          value={configured ? 'настроена' : 'не настроена'}
          tone={configured ? 'success' : 'neutral'}
          badge={configured ? 'ключ задан' : 'ключа нет'}
          hint="Возможность включается наличием ключа, а не флагом"
        />
        <Tile
          label="Ключ доступа"
          value={status.data.credential_state === 'configured' ? 'задан' : 'отсутствует'}
          hint="Значение не показывается и не логируется: живёт только в окружении сервера"
        />
        <Tile
          label="Адрес системы"
          value={<span className="mono text-sm">{status.data.base_url}</span>}
          hint="Не секрет: адрес есть в документации вендора"
        />
        <Tile
          label="Связанных проектов"
          value={String(status.data.linked_project_count)}
          hint="В текущем рабочем пространстве"
        />
      </div>

      {probe.data && (
        <div className="flex flex-col gap-[var(--s-3)] rounded-[var(--radius-md)] border border-border bg-surface p-[var(--s-5)]">
          <div className="flex flex-wrap items-center gap-[var(--s-4)]">
            <StatusBadge tone={probe.data.ok ? 'success' : 'danger'}>
              {probe.data.ok ? 'связь есть' : 'связи нет'}
            </StatusBadge>
            <span className="text-xs text-muted">
              проверено {new Date(probe.data.checked_at).toLocaleString('ru-RU')} ·{' '}
              {probe.data.duration_ms} мс
            </span>
          </div>
          {probe.data.ok ? (
            <p className="text-sm">Ключу доступно тендеров: {probe.data.tender_count ?? '—'}</p>
          ) : (
            <p className="text-sm text-danger">
              Код отказа: <span className="mono">{probe.data.error_code}</span>
            </p>
          )}
        </div>
      )}

      <div className="flex flex-col gap-[var(--s-3)] rounded-[var(--radius-md)] border border-dashed border-border-strong p-[var(--s-5)]">
        <h3 className="text-micro font-semibold tracking-[0.06em] text-muted uppercase">
          Связь проекта с тендером
        </h3>
        <p className="max-w-[70ch] text-sm text-muted">
          Перепривязка и отвязка выполняются из карточки проекта и требуют подтверждения: это
          административное событие, а не редактирование. Обычное переименование проекта из TenderHUB
          меняет только местное имя — каноническое название принадлежит внешней системе.
        </p>
        <p className="text-micro text-muted">
          Операции доступны в API:{' '}
          <span className="mono">/admin/integrations/tenderhub/projects/…</span>
        </p>
      </div>
    </Section>
  );
};

export default Page;
