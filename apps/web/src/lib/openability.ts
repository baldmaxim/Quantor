import type { DocumentRead, DocumentRevisionRead } from '@quantor/api-client';

/**
 * Можно ли открыть ревизию в рабочей области.
 *
 * Единственное место, где принимается это решение. Раньше оно было записано одним
 * условием прямо в карточке проекта — `processing_status === 'ready'`, — и обычный PDF
 * не открывался никогда: распознавание к нему не применяли, и статус навсегда оставался
 * `unprocessed`.
 *
 * Просмотр зависит от подготовки листов, а не от распознавания. Распознавание —
 * независимый необязательный слой поверх того же документа (ADR-0016), и на открытие
 * чертежа оно не влияет ни в какую сторону.
 */

/** Документ, который портал умеет показывать в рабочей области. Пакет — архив, BIM не разбираем. */
export const isViewable = (document: DocumentRead): boolean => document.document_kind === 'pdf';

export type OpenState =
  | { readonly kind: 'openable' }
  /** Геометрия ещё извлекается: листов пока нет или они неполны. */
  | { readonly kind: 'preparing' }
  /** Извлечь геометрию не удалось — честно показываем код причины. */
  | { readonly kind: 'geometry_failed'; readonly errorCode: string | null }
  /** Геометрия не в работе, но показывать нечего. */
  | { readonly kind: 'no_sheets' }
  /** Документ не открывается в просмотрщике по своей природе. */
  | { readonly kind: 'not_viewable' };

/**
 * Состояние одной ревизии.
 *
 * `processing_status` здесь не участвует намеренно: он описывает импорт распознанного
 * пакета. Открываемость определяют вид документа, готовность геометрии и наличие листов.
 *
 * Значение `not_applicable` вместе с листами — это ревизия, пришедшая из пакета до
 * появления извлечения геометрии: листы у неё есть, показать её можно, а обещать
 * готовность геометрии нельзя. Ровно это и означает ветка ниже.
 */
export const revisionOpenState = (
  document: DocumentRead,
  revision: DocumentRevisionRead,
): OpenState => {
  if (!isViewable(document)) return { kind: 'not_viewable' };

  if (revision.geometry_status === 'failed') {
    return { kind: 'geometry_failed', errorCode: revision.geometry_error_code };
  }

  if (revision.geometry_status === 'pending' || revision.geometry_status === 'extracting') {
    return { kind: 'preparing' };
  }

  return revision.sheet_count > 0 ? { kind: 'openable' } : { kind: 'no_sheets' };
};

export const isOpenable = (document: DocumentRead, revision: DocumentRevisionRead): boolean =>
  revisionOpenState(document, revision).kind === 'openable';

/**
 * Последняя открываемая ревизия документа.
 *
 * Ревизии приходят от старой к новой — это гарантия API (`list_revisions` сортирует по
 * `created_at`, затем по идентификатору), закреплённая тестом на стороне сервера.
 * Поэтому нужную даёт обратный обход, а не повторная сортировка на клиенте.
 */
export const latestOpenableRevision = (
  document: DocumentRead,
  revisions: readonly DocumentRevisionRead[],
): DocumentRevisionRead | null => {
  for (let index = revisions.length - 1; index >= 0; index -= 1) {
    const revision = revisions[index];
    if (revision && isOpenable(document, revision)) return revision;
  }
  return null;
};

/** Состояние документа целиком: по его последней ревизии. */
export const documentOpenState = (
  document: DocumentRead,
  revisions: readonly DocumentRevisionRead[],
): OpenState | null => {
  if (latestOpenableRevision(document, revisions)) return { kind: 'openable' };

  const latest = revisions.at(-1);
  return latest ? revisionOpenState(document, latest) : null;
};

export interface IOpenTarget {
  readonly document: DocumentRead;
  readonly revision: DocumentRevisionRead;
}

/** Все документы проекта, которые уже можно открыть. */
export const openTargets = (
  documents: readonly DocumentRead[],
  revisionsOf: (documentId: string) => readonly DocumentRevisionRead[],
): readonly IOpenTarget[] =>
  documents.flatMap((document) => {
    const revision = latestOpenableRevision(document, revisionsOf(document.id));
    return revision ? [{ document, revision }] : [];
  });

/**
 * Куда ведёт верхняя кнопка «Открыть рабочую область».
 *
 * Выбор не зависит от порядка списка: берётся самая свежая открываемая ревизия проекта, а
 * при совпадении времени — наибольший идентификатор. Прежняя кнопка брала первый
 * подходящий элемент массива, и при двух готовых документах результат определялся
 * порядком выдачи.
 */
export const chooseOpenTarget = (targets: readonly IOpenTarget[]): IOpenTarget | null =>
  targets.reduce<IOpenTarget | null>((best, candidate) => {
    if (!best) return candidate;

    const a = candidate.revision;
    const b = best.revision;
    if (a.created_at !== b.created_at) return a.created_at > b.created_at ? candidate : best;
    return a.id > b.id ? candidate : best;
  }, null);

/**
 * Почему открывать нечего. Порядок ветвления — от самого обнадёживающего к худшему:
 * если хоть что-то готовится, пользователю нужно сказать именно это.
 */
export const noTargetReason = (states: readonly OpenState[]): string => {
  const has = (kind: OpenState['kind']) => states.some((state) => state.kind === kind);

  if (has('preparing')) return 'Готовим листы: подождите окончания подготовки';
  if (has('geometry_failed'))
    return 'Листы PDF не подготовлены — откройте документ и посмотрите причину';
  if (has('no_sheets')) return 'В документе нет листов';
  return 'Загрузите PDF — он откроется, как только будут готовы листы';
};
