'use client';

import type { PersonalTokenRead } from '@quantor/api-client';
import { useState, type FC } from 'react';

import { Button, EmptyState, ErrorState, SkeletonRows, StatusBadge, cx } from '@/components/ui';
import { env } from '@/lib/env';
import { errorMessage, extractCode, extractMessage } from '@/lib/errors';
import { formatWhen } from '@/lib/format';
import { usePersonalTokens, useRevokePersonalToken } from '@/lib/tender/queries';
import { scopesLabel } from '@/lib/tender/token-scopes';

import { TokenCreateDialog } from './TokenCreateDialog';

/**
 * Раздел «Доступ для TENDER»: личные токены для загрузки расчётов навыком `quantor-obmen`.
 * Токен принадлежит пользователю и действует в этом пространстве; полное значение показывается
 * один раз при создании.
 */

const TH = 'px-[var(--s-4)] py-[var(--s-3)] font-semibold';
const TD =
  'px-[var(--s-4)] py-[var(--s-3)] align-top text-sm max-md:flex max-md:justify-between max-md:gap-[var(--s-4)] max-md:px-0 max-md:py-[var(--s-1)] max-md:before:text-xs max-md:before:text-muted max-md:before:content-[attr(data-label)]';

const portalOrigin = (): string =>
  typeof window === 'undefined' ? env.apiBaseUrl : window.location.origin;

const TokenRow: FC<{
  readonly token: PersonalTokenRead;
  readonly busy: boolean;
  readonly onRevoke: () => void;
}> = ({ token, busy, onRevoke }) => {
  const dim = token.active ? '' : 'text-muted line-through';
  return (
    <tr className="border-b border-border last:border-b-0 max-md:flex max-md:flex-col max-md:px-[var(--s-5)] max-md:py-[var(--s-4)]">
      <td data-label="Название" className={cx(TD, '[overflow-wrap:anywhere]', dim)}>
        <span>{token.name}</span>
        <span className="block text-xs text-muted">{scopesLabel(token.scopes ?? [])}</span>
      </td>
      <td data-label="Префикс" className={cx(TD, 'mono text-xs')}>
        {/* Разрешение ИИ-чату по OAuth: значения qtk_ у него нет, чат входит сам. */}
        {token.client_name ? 'вход чата' : `${token.prefix}…`}
      </td>
      <td data-label="Создан" className={cx(TD, 'text-muted')}>
        {formatWhen(token.created_at)}
      </td>
      <td data-label="Последний вход" className={cx(TD, 'text-muted')}>
        {token.last_used_at ? formatWhen(token.last_used_at) : 'не использовался'}
      </td>
      <td data-label="Срок" className={cx(TD, 'text-muted')}>
        {token.expires_at ? formatWhen(token.expires_at) : 'бессрочный'}
      </td>
      <td className={cx(TD, 'max-md:justify-start')}>
        {token.revoked_at ? (
          <StatusBadge tone="danger">Отозван</StatusBadge>
        ) : token.active ? (
          <Button compact variant="danger" onClick={onRevoke} disabled={busy}>
            Отозвать
          </Button>
        ) : (
          <StatusBadge tone="neutral">Истёк</StatusBadge>
        )}
      </td>
    </tr>
  );
};

export const TokensTab: FC = () => {
  const tokens = usePersonalTokens(true);
  const revoke = useRevokePersonalToken();
  const [creating, setCreating] = useState(false);

  return (
    <div className="flex flex-col gap-[var(--s-5)]">
      <div className="flex flex-wrap items-center gap-[var(--s-4)]">
        <div className="flex min-w-0 flex-1 basis-[280px] flex-col gap-[var(--s-3)]">
          <p className="m-0 max-w-[70ch] text-sm text-muted">
            Доступ к порталу для TENDER, скриптов и ИИ-ассистентов (MCP). Загрузка расчётов TENDER:
          </p>
          <code className="mono block max-w-full overflow-x-auto rounded-[var(--radius-sm)] bg-surface-muted px-[var(--s-4)] py-[var(--s-3)] text-xs">
            python3 calc_push.py --portal {portalOrigin()} --token-file …
          </code>
        </div>
        <Button variant="primary" onClick={() => setCreating(true)}>
          Создать токен
        </Button>
      </div>

      {tokens.isPending && <SkeletonRows rows={3} />}
      {tokens.isError && (
        <ErrorState
          title="Токены не загрузились"
          code={extractCode(tokens.error)}
          description={extractMessage(tokens.error) ?? errorMessage(extractCode(tokens.error))}
          onRetry={() => void tokens.refetch()}
        />
      )}
      {tokens.data && tokens.data.length === 0 && <EmptyState compact title="Токенов пока нет" />}
      {tokens.data && tokens.data.length > 0 && (
        <div className="rounded-[var(--radius-md)] border border-border-strong bg-surface">
          <table
            aria-label="Личные токены"
            className="w-full border-collapse text-left max-md:block"
          >
            <thead className="max-md:sr-only">
              <tr className="border-b border-border-strong bg-surface-muted text-micro font-semibold tracking-[0.06em] text-muted uppercase">
                <th scope="col" className={TH}>
                  Название
                </th>
                <th scope="col" className={TH}>
                  Префикс
                </th>
                <th scope="col" className={TH}>
                  Создан
                </th>
                <th scope="col" className={TH}>
                  Последний вход
                </th>
                <th scope="col" className={TH}>
                  Срок
                </th>
                <th scope="col" className={TH}>
                  Действия
                </th>
              </tr>
            </thead>
            <tbody className="max-md:block">
              {tokens.data.map((token) => (
                <TokenRow
                  key={token.id}
                  token={token}
                  busy={revoke.isPending}
                  onRevoke={() => revoke.mutate(token.id)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
      {revoke.isError && (
        <p role="alert" className="m-0 text-sm text-danger">
          {extractMessage(revoke.error) ?? errorMessage(extractCode(revoke.error))}
        </p>
      )}

      <TokenCreateDialog open={creating} onClose={() => setCreating(false)} />
    </div>
  );
};
