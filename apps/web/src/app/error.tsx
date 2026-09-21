'use client';

import { useEffect } from 'react';

import { Button, ButtonLink, ErrorState } from '@/components/ui';
import { reportClientError } from '@/lib/report';

/**
 * Граница ошибок маршрута.
 *
 * Без неё сбой в любом компоненте оставляет пустой экран, и пользователь не понимает,
 * сломался ли портал или просто долго грузится. Здесь он видит, что произошло,
 * и может попробовать снова, не перезагружая вкладку.
 */
const RouteError = ({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) => {
  useEffect(() => {
    reportClientError(error, 'route');
  }, [error]);

  return (
    <main className="grid min-h-dvh place-items-center p-[var(--s-7)]">
      <div className="flex w-full max-w-[560px] flex-col gap-[var(--s-5)]">
        <ErrorState
          title="Что-то пошло не так"
          code={error.digest ?? null}
          description="Страница не отрисовалась. Попробуйте ещё раз — если повторяется, сообщите код выше."
        />
        <div className="flex gap-[var(--s-4)]">
          <Button variant="primary" onClick={reset}>
            Попробовать снова
          </Button>
          <ButtonLink href="/projects">К списку проектов</ButtonLink>
        </div>
      </div>
    </main>
  );
};

export default RouteError;
