'use client';

import type { SettingStateRead } from '@quantor/api-client';
import { Button, ErrorState, SkeletonRows, StatusBadge } from '@quantor/ui';
import { useState } from 'react';

import { Section } from '@/components/common/Section';
import { useResetSetting, useSetSetting, useSettings } from '@/lib/queries';
import { sourceLabel, sourceTone } from '@/lib/status';

/**
 * Управляемые настройки.
 *
 * Страница строится из метаданных реестра, а не из зашитой здесь копии списка: тип,
 * пределы и допустимые значения приходят с сервера. Это и отличает её от универсальной
 * формы JSON — администратор не может задать то, чего настройка не принимает.
 *
 * Рядом со значением всегда видно, откуда оно взялось. «Включено» без ответа на вопрос
 * «кем и где» — это половина сведений, по которой ничего не починить.
 */

const scopeOf = (setting: SettingStateRead): 'system' | 'workspace' =>
  setting.allowed_scopes.includes('system') ? 'system' : 'workspace';

const Row = ({ setting }: { setting: SettingStateRead }) => {
  const [draft, setDraft] = useState<string>(String(setting.value));
  const save = useSetSetting();
  const reset = useResetSetting();

  const scope = scopeOf(setting);
  const dirty = draft !== String(setting.value);
  const overridden = setting.source !== 'default';
  const busy = save.isPending || reset.isPending;

  const parse = (raw: string): unknown => (setting.value_type === 'integer' ? Number(raw) : raw);

  return (
    <tr>
      <td>
        <div className="flex flex-col gap-[var(--s-2)]">
          <span className="font-medium">{setting.title}</span>
          <span className="mono text-micro text-muted">{setting.key}</span>
          <span className="max-w-[52ch] text-xs text-muted">{setting.description}</span>
        </div>
      </td>

      <td>
        <div className="flex flex-col gap-[var(--s-3)]">
          {setting.value_type === 'enum' ? (
            <select
              value={draft}
              disabled={!setting.editable || busy}
              onChange={(event) => setDraft(event.target.value)}
              className="h-[var(--h-ctl)] rounded-[var(--radius-sm)] border border-border bg-surface-muted px-[var(--s-4)] text-sm disabled:opacity-45"
            >
              {(setting.choices ?? []).map((choice) => (
                <option key={choice} value={choice}>
                  {choice}
                </option>
              ))}
            </select>
          ) : (
            <input
              value={draft}
              disabled={!setting.editable || busy}
              inputMode={setting.value_type === 'integer' ? 'numeric' : 'text'}
              onChange={(event) => setDraft(event.target.value)}
              className="h-[var(--h-ctl)] w-[220px] rounded-[var(--radius-sm)] border border-border bg-surface-muted px-[var(--s-4)] text-sm disabled:opacity-45"
            />
          )}
          {(setting.minimum !== null || setting.maximum !== null) && (
            <span className="text-micro text-muted">
              допустимо: {setting.minimum ?? '—'} … {setting.maximum ?? '—'}
            </span>
          )}
        </div>
      </td>

      <td>
        <div className="flex flex-col gap-[var(--s-2)]">
          <StatusBadge tone={sourceTone(setting.source)}>{sourceLabel(setting.source)}</StatusBadge>
          {setting.updated_at && (
            <span className="text-micro text-muted">
              изменено {setting.updated_at.slice(0, 16)}
            </span>
          )}
          {!setting.editable && (
            <span className="text-micro text-warning">
              задано окружением, из портала не меняется
            </span>
          )}
          <span className="text-micro text-muted">
            по умолчанию: {String(setting.default_value)}
          </span>
        </div>
      </td>

      <td>
        <div className="flex flex-wrap gap-[var(--s-3)]">
          <Button
            compact
            variant="primary"
            disabled={!setting.editable || !dirty || busy}
            onClick={() => save.mutate({ key: setting.key, scope, value: parse(draft) })}
          >
            Сохранить
          </Button>
          <Button
            compact
            disabled={!setting.editable || !overridden || busy}
            onClick={() => {
              reset.mutate({ key: setting.key, scope });
              setDraft(String(setting.default_value));
            }}
          >
            Сбросить
          </Button>
        </div>
        {(save.isError || reset.isError) && (
          <p className="mt-[var(--s-3)] text-xs text-danger">
            Сервер отклонил значение. Проверьте пределы.
          </p>
        )}
      </td>
    </tr>
  );
};

const Page = () => {
  const settings = useSettings();

  if (settings.isPending) return <SkeletonRows rows={4} />;
  if (settings.isError) {
    return (
      <ErrorState
        title="Настройки не загрузились"
        onRetry={() => void settings.refetch()}
        description="Проверьте, что API отвечает."
      />
    );
  }

  return (
    <Section
      title="Настройки"
      description="Значения, которыми управляет администратор. Определения живут в коде: изменить можно значение, но не набор и не пределы."
    >
      <div className="table-scroll rounded-[var(--radius-md)] border border-border bg-surface">
        <table className="admin-table">
          <thead>
            <tr>
              <th>Настройка</th>
              <th>Значение</th>
              <th>Откуда</th>
              <th>Действия</th>
            </tr>
          </thead>
          <tbody>
            {settings.data.map((setting) => (
              <Row key={setting.key} setting={setting} />
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  );
};

export default Page;
