'use client';

import type { FC } from 'react';

import { errorMessage, extractCode, extractMessage } from '@/lib/errors';
import { useContentUrl } from '@/lib/queries';

/**
 * Предпросмотр страницы PDF встроенным просмотрщиком браузера.
 * Ссылка на файл временная и подписанная; номер страницы уходит во фрагмент `#page=N`.
 */

interface IPreviewProps {
  readonly revisionId: string;
  readonly pageIndex: number;
  readonly label: string;
}

export const SheetPagePreview: FC<IPreviewProps> = ({ revisionId, pageIndex, label }) => {
  const { data, error, isError } = useContentUrl(revisionId);

  if (isError) {
    return (
      <p role="alert" className="text-sm text-danger">
        {extractMessage(error) ?? errorMessage(extractCode(error))}
      </p>
    );
  }

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-2)] lg:h-full">
      {data === undefined ? (
        <div className="flex h-[50dvh] w-full items-center justify-center rounded border border-border bg-surface-muted text-sm text-muted lg:h-full lg:min-h-[60dvh]">
          Загружаем лист…
        </div>
      ) : (
        <iframe
          title={`Предпросмотр: ${label}`}
          src={`${data.url}#page=${pageIndex + 1}`}
          className="h-[50dvh] w-full rounded border border-border bg-surface-muted lg:h-full lg:min-h-[60dvh]"
        />
      )}
      <p className="text-xs text-muted">
        Колесо мыши и кнопки просмотрщика браузера — масштаб и прокрутка.
      </p>
    </div>
  );
};
