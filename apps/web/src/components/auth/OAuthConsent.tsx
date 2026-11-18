'use client';

import {
  oauthAuthorizeCheck,
  oauthAuthorizeDecide,
  type OAuthAuthorizeInfo,
} from '@quantor/api-client';
import { useEffect, useMemo, useState } from 'react';

import { Button, ErrorState } from '@/components/ui';
import { errorMessage, extractCode, extractMessage } from '@/lib/errors';

/**
 * Решение человека о доступе ИИ-чата (ADR-0054).
 *
 * Параметры запроса чата идут в API как пришли; API отвечает, что за чат, куда уйдёт ответ и
 * что он просит, либо адресом, куда сразу вернуть чат с ошибкой. Чтение есть всегда, загрузку
 * можно снять. После решения — полный переход по адресу из ответа API (только зарегистрированный
 * у чата адрес из белого списка портала).
 */

const READ = 'read';

interface IOAuthConsentProps {
  query: string;
}

interface IFailure {
  code: string;
  text: string;
}

const failureOf = (error: unknown): IFailure => {
  const code = extractCode(error);
  return { code, text: errorMessage(code, extractMessage(error)) };
};

export const OAuthConsent = ({ query }: IOAuthConsentProps) => {
  const params = useMemo(() => Object.fromEntries(new URLSearchParams(query)), [query]);
  const [info, setInfo] = useState<OAuthAuthorizeInfo | null>(null);
  const [scopes, setScopes] = useState<Set<string>>(new Set());
  const [failure, setFailure] = useState<IFailure | null>(null);
  const [pending, setPending] = useState<'approve' | 'deny' | null>(null);

  useEffect(() => {
    let cancelled = false;
    oauthAuthorizeCheck({ throwOnError: true, query: params })
      .then(({ data }) => {
        if (cancelled) return;
        if (data.error_redirect) {
          window.location.assign(data.error_redirect);
          return;
        }
        setInfo(data);
        setScopes(new Set(data.scopes ?? []));
      })
      .catch((error: unknown) => {
        if (!cancelled) setFailure(failureOf(error));
      });
    return () => {
      cancelled = true;
    };
  }, [params]);

  const decide = async (approve: boolean) => {
    setFailure(null);
    setPending(approve ? 'approve' : 'deny');
    try {
      const { data } = await oauthAuthorizeDecide({
        throwOnError: true,
        body: { params, approve, scopes: approve ? [...scopes] : [] },
      });
      window.location.assign(data.redirect_to);
    } catch (error) {
      setPending(null);
      setFailure(failureOf(error));
    }
  };

  if (!info) {
    return failure ? (
      <ErrorState
        title="Запрос чата не принят"
        code={failure.code}
        description={`${failure.text}. Начните подключение в чате заново.`}
      />
    ) : (
      <p className="text-center text-sm text-muted">Проверяем запрос чата…</p>
    );
  }

  const requested = info.scopes ?? [];
  const titles = info.scope_titles ?? {};

  return (
    <div className="flex flex-col gap-[var(--s-5)]">
      <div className="flex flex-col gap-[var(--s-2)] text-sm">
        <p>
          <span className="font-semibold">«{info.client_name}»</span> просит доступ к Quantor от
          вашего имени.
        </p>
        <p className="text-muted">
          Ответ уйдёт на <span className="mono">{info.redirect_host}</span>
          {info.local_app ? ' — программа на этом компьютере' : ''}.
          {info.workspace_name ? ` Пространство: ${info.workspace_name}.` : ''}
        </p>
        {info.already_connected && (
          <p className="text-muted">Этот чат уже подключён: разрешение обновится.</p>
        )}
      </div>

      <fieldset className="flex flex-col gap-[var(--s-3)]">
        <legend className="mb-[var(--s-2)] text-sm font-semibold">Что разрешить</legend>
        {requested.map((scope) => (
          <label key={scope} className="flex items-start gap-[var(--s-2)] text-sm">
            <input
              type="checkbox"
              className="mt-[3px]"
              checked={scope === READ || scopes.has(scope)}
              disabled={scope === READ || pending !== null}
              onChange={(event) => {
                const next = new Set(scopes);
                if (event.target.checked) next.add(scope);
                else next.delete(scope);
                setScopes(next);
              }}
            />
            <span>{titles[scope] ?? scope}</span>
          </label>
        ))}
      </fieldset>

      <p className="text-xs text-muted">
        Права не шире ваших. Отключить чат можно в любой момент в разделе «Доступ».
      </p>

      {failure && (
        <ErrorState title="Не получилось" code={failure.code} description={failure.text} />
      )}

      <div className="flex flex-col gap-[var(--s-3)]">
        <Button
          type="button"
          variant="primary"
          loading={pending === 'approve'}
          loadingLabel="Разрешаем…"
          disabled={pending !== null}
          onClick={() => void decide(true)}
        >
          Разрешить
        </Button>
        <Button
          type="button"
          loading={pending === 'deny'}
          loadingLabel="Отказываем…"
          disabled={pending !== null}
          onClick={() => void decide(false)}
        >
          Отказать
        </Button>
      </div>
    </div>
  );
};
