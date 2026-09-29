'use client';

import { loginWithPassword } from '@quantor/api-client';
import Link from 'next/link';
import { useState, type FormEvent } from 'react';

import { TextField } from '@/components/auth/TextField';
import { Button, ErrorState } from '@/components/ui';
import { errorMessage, extractCode, extractMessage } from '@/lib/errors';

/**
 * Вход по почте и паролю (ADR-0031).
 *
 * После входа — полный переход, а не маршрутизатор: серверная оболочка портала должна
 * прочитать только что выставленную cookie сеанса, а переход внутри приложения её не
 * спросил бы. Пароль, выданный администратором, сначала меняется.
 */

interface ISignInFormProps {
  next: string;
}

export const SignInForm = ({ next }: ISignInFormProps) => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<{ code: string; text: string } | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFailure(null);
    setPending(true);

    try {
      const response = await loginWithPassword({ throwOnError: true, body: { email, password } });
      const target = response.data?.must_change_password
        ? `/account/password?next=${encodeURIComponent(next)}`
        : next;
      window.location.assign(target);
    } catch (error) {
      setPending(false);
      const code = extractCode(error);
      setFailure({ code, text: errorMessage(code, extractMessage(error)) });
    }
  };

  return (
    <form onSubmit={(event) => void submit(event)} className="flex flex-col gap-[var(--s-5)]">
      <TextField
        label="Почта"
        type="email"
        name="email"
        autoComplete="username"
        inputMode="email"
        autoFocus
        required
        value={email}
        disabled={pending}
        onChange={(event) => setEmail(event.target.value)}
      />
      <TextField
        label="Пароль"
        type="password"
        name="password"
        autoComplete="current-password"
        required
        value={password}
        disabled={pending}
        onChange={(event) => setPassword(event.target.value)}
      />

      {failure && (
        <ErrorState title="Вход не выполнен" code={failure.code} description={failure.text} />
      )}

      <Button
        type="submit"
        variant="primary"
        loading={pending}
        loadingLabel="Входим…"
        disabled={!email.trim() || !password}
        className="max-md:h-[44px]"
      >
        Войти
      </Button>

      <p className="text-center text-sm text-muted">
        Нет доступа?{' '}
        <Link href="/register" className="text-text underline underline-offset-4">
          Подать заявку
        </Link>
      </p>
    </form>
  );
};
