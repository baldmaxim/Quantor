'use client';

import { changePassword } from '@quantor/api-client';
import { useState, type FormEvent } from 'react';

import { TextField } from '@/components/auth/TextField';
import { Button, ErrorState } from '@/components/ui';
import { errorMessage, extractCode, extractMessage } from '@/lib/errors';

/**
 * Смена собственного пароля.
 *
 * Текущий пароль спрашивается и тогда, когда его выдал администратор: без него чужой
 * человек у незаблокированного экрана сменил бы пароль и забрал учётную запись.
 * Подтверждение CSRF добавляет перехватчик клиента API.
 */

const MIN_PASSWORD_LENGTH = 10;

interface IChangePasswordFormProps {
  next: string;
}

export const ChangePasswordForm = ({ next }: IChangePasswordFormProps) => {
  const [current, setCurrent] = useState('');
  const [password, setPassword] = useState('');
  const [repeat, setRepeat] = useState('');
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<{ code: string; text: string } | null>(null);

  const mismatch = repeat.length > 0 && repeat !== password;
  const canSubmit =
    current.length > 0 && password.length >= MIN_PASSWORD_LENGTH && repeat === password && !pending;

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit) return;
    setFailure(null);
    setPending(true);

    try {
      await changePassword({
        throwOnError: true,
        body: { current_password: current, new_password: password },
      });
      window.location.assign(next);
    } catch (error) {
      setPending(false);
      const code = extractCode(error);
      // Здесь сообщение сервера точнее общего: «Текущий пароль неверен», а не
      // «Неверная почта или пароль» формы входа.
      setFailure({ code, text: extractMessage(error) ?? errorMessage(code) });
    }
  };

  return (
    <form onSubmit={(event) => void submit(event)} className="flex flex-col gap-[var(--s-5)]">
      <TextField
        label="Текущий пароль"
        type="password"
        name="current-password"
        autoComplete="current-password"
        autoFocus
        required
        value={current}
        disabled={pending}
        onChange={(event) => setCurrent(event.target.value)}
      />
      <TextField
        label="Новый пароль"
        type="password"
        name="new-password"
        autoComplete="new-password"
        hint={`Не короче ${MIN_PASSWORD_LENGTH} символов.`}
        required
        value={password}
        disabled={pending}
        onChange={(event) => setPassword(event.target.value)}
      />
      <TextField
        label="Новый пароль ещё раз"
        type="password"
        name="repeat-password"
        autoComplete="new-password"
        required
        value={repeat}
        disabled={pending}
        aria-invalid={mismatch || undefined}
        hint={mismatch ? 'Пароли не совпадают' : undefined}
        onChange={(event) => setRepeat(event.target.value)}
      />

      {failure && (
        <ErrorState title="Пароль не сменён" code={failure.code} description={failure.text} />
      )}

      <Button
        type="submit"
        variant="primary"
        loading={pending}
        loadingLabel="Сохраняем…"
        disabled={!canSubmit}
        className="max-md:h-[44px]"
      >
        Сменить пароль
      </Button>
    </form>
  );
};
