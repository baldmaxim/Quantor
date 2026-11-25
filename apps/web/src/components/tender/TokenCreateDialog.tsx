'use client';

import type { PersonalTokenCreated } from '@quantor/api-client';
import { useState, type FC, type FormEvent } from 'react';

import { Button, Dialog, DialogActions } from '@/components/ui';
import { ClearableInput } from '@/components/ui/ClearableInput';
import { errorMessage, extractCode, extractMessage } from '@/lib/errors';
import { useCreatePersonalToken } from '@/lib/tender/queries';
import { TOKEN_SCOPES, type TokenScope } from '@/lib/tender/token-scopes';

/**
 * Окно создания токена в два шага: название и срок -> значение токена. Значение показывается один
 * раз и не хранится нигде, кроме состояния окна: после закрытия оно стирается.
 */

interface IDialogProps {
  readonly open: boolean;
  readonly onClose: () => void;
}

const LIFETIMES: readonly { readonly value: string; readonly label: string }[] = [
  { value: '30', label: '30 дней' },
  { value: '90', label: '90 дней' },
  { value: '180', label: '180 дней' },
  { value: '365', label: '1 год' },
  { value: 'none', label: 'Без срока' },
];

const FIELD_LABEL = 'flex flex-col gap-[var(--s-2)] text-sm';

export const TokenCreateDialog: FC<IDialogProps> = ({ open, onClose }) => {
  const create = useCreatePersonalToken();
  const [name, setName] = useState('');
  const [lifetime, setLifetime] = useState('90');
  const [scopes, setScopes] = useState<ReadonlySet<TokenScope>>(new Set(['tender']));
  const [created, setCreated] = useState<PersonalTokenCreated | null>(null);
  const [copied, setCopied] = useState<'done' | 'failed' | null>(null);

  const submit = (event: FormEvent): void => {
    event.preventDefault();
    if (name.trim() === '' || scopes.size === 0) return;
    create.mutate(
      {
        name: name.trim(),
        expires_in_days: lifetime === 'none' ? null : Number(lifetime),
        scopes: TOKEN_SCOPES.map((scope) => scope.value).filter((value) => scopes.has(value)),
      },
      { onSuccess: setCreated },
    );
  };

  const copy = async (value: string): Promise<void> => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied('done');
    } catch {
      setCopied('failed');
    }
  };

  const reset = (): void => {
    create.reset();
    setName('');
    setLifetime('90');
    setScopes(new Set(['tender']));
    setCreated(null);
    setCopied(null);
  };

  const busy = create.isPending;

  return (
    <Dialog
      open={open}
      onClose={onClose}
      busy={busy}
      onExited={reset}
      title={created ? 'Токен создан' : 'Новый токен'}
      description={
        created
          ? 'Скопируйте токен сейчас: больше мы его не покажем.'
          : 'Токен действует от вашего имени в этом пространстве. Что он может - выберите ниже, в пределах ваших прав.'
      }
      footer={
        created ? (
          <DialogActions>
            <Button variant="primary" onClick={onClose}>
              Готово
            </Button>
          </DialogActions>
        ) : (
          <DialogActions>
            <Button onClick={onClose} disabled={busy}>
              Отмена
            </Button>
            <Button
              variant="primary"
              type="submit"
              form="tender-token-form"
              disabled={busy || name.trim() === '' || scopes.size === 0}
            >
              {busy ? 'Создаём…' : 'Создать'}
            </Button>
          </DialogActions>
        )
      }
    >
      {created ? (
        <div className="flex flex-col gap-[var(--s-4)]">
          <input
            readOnly
            aria-label="Токен"
            value={created.token}
            onFocus={(event) => event.currentTarget.select()}
            className="mono h-[44px] w-full rounded-[var(--radius-sm)] border border-border-control bg-surface-muted px-[var(--s-4)] text-base text-text md:h-[var(--h-ctl)] md:text-sm"
          />
          <div className="flex flex-wrap items-center gap-[var(--s-4)]">
            <Button onClick={() => void copy(created.token)}>Копировать</Button>
            {copied === 'done' && (
              <span role="status" className="text-sm text-success">
                Скопировано
              </span>
            )}
            {copied === 'failed' && (
              <span role="status" className="text-sm text-danger">
                Не удалось скопировать — выделите и скопируйте вручную
              </span>
            )}
          </div>
          <p role="alert" className="m-0 text-sm text-warning">
            Токен показывается один раз. Потеряете — отзовите его и создайте новый.
          </p>
        </div>
      ) : (
        <form id="tender-token-form" onSubmit={submit} className="flex flex-col gap-[var(--s-5)]">
          <label className={FIELD_LABEL}>
            Название
            <ClearableInput
              label="Название токена"
              placeholder="Например, ноутбук сметчика"
              value={name}
              maxLength={80}
              autoFocus
              onChange={(event) => setName(event.target.value)}
              onClear={() => setName('')}
              wrapperClassName="flex w-full"
            />
          </label>
          <label className={FIELD_LABEL}>
            Срок действия
            <select
              value={lifetime}
              onChange={(event) => setLifetime(event.target.value)}
              className="h-[44px] w-full rounded-[var(--radius-sm)] border border-border-control bg-surface px-[var(--s-4)] text-base text-text md:h-[var(--h-ctl)] md:text-sm"
            >
              {LIFETIMES.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <fieldset className="m-0 flex flex-col gap-[var(--s-2)] border-0 p-0">
            <legend className="mb-[var(--s-2)] text-sm">Для чего токен</legend>
            {TOKEN_SCOPES.map((scope) => (
              <label key={scope.value} className="flex items-start gap-[var(--s-2)] text-sm">
                <input
                  type="checkbox"
                  className="mt-[3px]"
                  checked={scopes.has(scope.value)}
                  onChange={(event) => {
                    const next = new Set(scopes);
                    if (event.target.checked) next.add(scope.value);
                    else next.delete(scope.value);
                    setScopes(next);
                  }}
                />
                <span>
                  {scope.label}
                  <span className="block text-xs text-muted">{scope.hint}</span>
                </span>
              </label>
            ))}
            {scopes.size === 0 && (
              <span role="status" className="text-xs text-danger">
                Отметьте хотя бы одну область
              </span>
            )}
          </fieldset>
          {create.isError && (
            <p role="alert" className="m-0 text-sm text-danger">
              {extractMessage(create.error) ?? errorMessage(extractCode(create.error))}
            </p>
          )}
        </form>
      )}
    </Dialog>
  );
};
