'use client';

import { Button } from '@quantor/ui';

import type { AuditQuery } from '@/lib/queries';

/**
 * Фильтры журнала.
 *
 * Уходят на сервер, а не применяются к уже загруженной странице. Разница не
 * косметическая: фильтрация на клиенте показала бы отказы только из тех пятидесяти
 * записей, что успели загрузиться, — и создала бы впечатление, что отказов почти нет.
 *
 * Действия перечислены списком, а не вводятся строкой: словарь конечен и задан кодом,
 * а свободный ввод здесь означал бы поиск по опечаткам.
 */

const ACTIONS: readonly { value: string; label: string }[] = [
  { value: '', label: 'все действия' },
  { value: 'setting_override_set', label: 'настройка изменена' },
  { value: 'setting_override_deleted', label: 'настройка сброшена' },
  { value: 'feature_flag_override_set', label: 'флаг изменён' },
  { value: 'feature_flag_override_deleted', label: 'флаг сброшен' },
  { value: 'tenderhub_connection_tested', label: 'проверка TenderHUB' },
  { value: 'tenderhub_project_rebound', label: 'перепривязка тендера' },
  { value: 'tenderhub_project_unlinked', label: 'отвязка тендера' },
  { value: 'job_retried', label: 'повтор задания' },
  { value: 'job_cancelled', label: 'отмена задания' },
  { value: 'login_succeeded', label: 'вход' },
  { value: 'logout', label: 'выход' },
  { value: 'permission_denied', label: 'отказ в доступе' },
];

const RESULTS = [
  { value: '', label: 'любой итог' },
  { value: 'success', label: 'выполнено' },
  { value: 'failure', label: 'отказ' },
  { value: 'denied', label: 'запрещено' },
] as const;

const FIELD =
  'h-[var(--h-ctl)] rounded-[var(--radius-sm)] border border-border bg-surface-muted px-[var(--s-4)] text-sm';

interface IAuditFiltersProps {
  value: AuditQuery;
  onChange: (next: AuditQuery) => void;
}

export const AuditFilters = ({ value, onChange }: IAuditFiltersProps) => {
  // Смена фильтра возвращает на первую страницу: остаться на пятой странице выборки,
  // в которой всего две записи, — верный способ решить, что журнал пуст.
  const update = (patch: Partial<AuditQuery>) => onChange({ ...value, ...patch, offset: 0 });

  const active =
    Boolean(value.action) || Boolean(value.result) || Boolean(value.since) || Boolean(value.until);

  return (
    <div className="flex flex-wrap items-end gap-[var(--s-4)]">
      <label className="flex flex-col gap-[var(--s-2)]">
        <span className="text-micro text-muted">Действие</span>
        <select
          className={FIELD}
          value={value.action ?? ''}
          onChange={(event) => update({ action: event.target.value || undefined })}
        >
          {ACTIONS.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-[var(--s-2)]">
        <span className="text-micro text-muted">Итог</span>
        <select
          className={FIELD}
          value={value.result ?? ''}
          onChange={(event) =>
            update({ result: (event.target.value || undefined) as AuditQuery['result'] })
          }
        >
          {RESULTS.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-[var(--s-2)]">
        <span className="text-micro text-muted">Не раньше</span>
        <input
          type="date"
          className={FIELD}
          value={value.since?.slice(0, 10) ?? ''}
          onChange={(event) =>
            update({ since: event.target.value ? `${event.target.value}T00:00:00Z` : undefined })
          }
        />
      </label>

      <label className="flex flex-col gap-[var(--s-2)]">
        <span className="text-micro text-muted">Не позже</span>
        <input
          type="date"
          className={FIELD}
          value={value.until?.slice(0, 10) ?? ''}
          onChange={(event) =>
            update({ until: event.target.value ? `${event.target.value}T23:59:59Z` : undefined })
          }
        />
      </label>

      <Button disabled={!active} onClick={() => onChange({ limit: value.limit, offset: 0 })}>
        Сбросить
      </Button>
    </div>
  );
};
