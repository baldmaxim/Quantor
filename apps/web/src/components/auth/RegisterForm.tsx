'use client';

import { register } from '@quantor/api-client';
import Link from 'next/link';
import { useState, type FormEvent } from 'react';

import { TextField } from '@/components/auth/TextField';
import { Button, ErrorState } from '@/components/ui';
import { errorMessage, extractCode, extractMessage } from '@/lib/errors';

/**
 * Заявка на доступ.
 *
 * Регистрация не даёт доступа сама по себе: заявку одобряет администратор и сразу
 * назначает пространство и роль. Поэтому после отправки — не вход, а объяснение, что
 * будет дальше. Ответ сервера одинаков для нового и занятого адреса, и экран тоже.
 */

const MIN_PASSWORD_LENGTH = 10;

export const RegisterForm = () => {
  const [email, setEmail] = useState('');
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [repeat, setRepeat] = useState('');
  const [pending, setPending] = useState(false);
  const [sent, setSent] = useState(false);
  const [failure, setFailure] = useState<{ code: string; text: string } | null>(null);

  const mismatch = repeat.length > 0 && repeat !== password;
  const canSubmit =
    email.trim().length > 0 &&
    name.trim().length > 0 &&
    password.length >= MIN_PASSWORD_LENGTH &&
    repeat === password &&
    !pending;

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit) return;
    setFailure(null);
    setPending(true);

    try {
      await register({
        throwOnError: true,
        body: { email: email.trim(), display_name: name.trim(), password },
      });
      setSent(true);
    } catch (error) {
      const code = extractCode(error);
      setFailure({ code, text: errorMessage(code, extractMessage(error)) });
    } finally {
      setPending(false);
    }
  };

  if (sent) {
    return (
      <div className="flex flex-col gap-[var(--s-5)] text-center">
        <p className="text-sm">
          Заявка отправлена. Администратор рассмотрит её и назначит рабочее пространство. После
          одобрения войдите с этим адресом и паролем.
        </p>
        <Link href="/signed-out" className="text-sm text-text underline underline-offset-4">
          Ко входу
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={(event) => void submit(event)} className="flex flex-col gap-[var(--s-5)]">
      <TextField
        label="Почта"
        type="email"
        name="email"
        autoComplete="email"
        inputMode="email"
        autoFocus
        required
        value={email}
        disabled={pending}
        onChange={(event) => setEmail(event.target.value)}
      />
      <TextField
        label="Имя и фамилия"
        name="name"
        autoComplete="name"
        required
        value={name}
        disabled={pending}
        onChange={(event) => setName(event.target.value)}
      />
      <TextField
        label="Пароль"
        type="password"
        name="new-password"
        autoComplete="new-password"
        hint={`Не короче ${MIN_PASSWORD_LENGTH} символов. Фраза из нескольких слов надёжнее.`}
        required
        value={password}
        disabled={pending}
        onChange={(event) => setPassword(event.target.value)}
      />
      <TextField
        label="Пароль ещё раз"
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
        <ErrorState title="Заявка не отправлена" code={failure.code} description={failure.text} />
      )}

      <Button
        type="submit"
        variant="primary"
        loading={pending}
        loadingLabel="Отправляем…"
        disabled={!canSubmit}
        className="max-md:h-[44px]"
      >
        Отправить заявку
      </Button>

      <p className="text-center text-sm text-muted">
        Уже есть доступ?{' '}
        <Link href="/signed-out" className="text-text underline underline-offset-4">
          Войти
        </Link>
      </p>
    </form>
  );
};
