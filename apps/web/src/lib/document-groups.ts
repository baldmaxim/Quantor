import type { DocumentKind } from '@quantor/api-client';

/**
 * Группы документов для переключателя в карточке проекта.
 *
 * Распознанный пакет после импорта сам по себе не нужен: работают с PDF, извлечённым из
 * него, а архив остаётся неизменяемым источником (ADR-0007). Показанные подряд, архив и
 * его PDF удваивают список и выглядят как дубли — поэтому по умолчанию виден только PDF.
 * BIM-модели лишь хранятся, но прятать их совсем нельзя: загруженный файл не должен
 * пропадать из виду.
 */

export type DocumentGroup = 'pdf' | 'zip' | 'bim';

/** Порядок сегментов; он же порядок выбора по умолчанию. */
const GROUP_ORDER: readonly DocumentGroup[] = ['pdf', 'zip', 'bim'];

export const DOCUMENT_GROUP_LABELS: Readonly<Record<DocumentGroup, string>> = {
  pdf: 'PDF',
  zip: 'ZIP',
  bim: 'BIM',
};

export const documentGroup = (kind: DocumentKind): DocumentGroup => {
  if (kind === 'pdf') return 'pdf';
  if (kind === 'recognized_package') return 'zip';
  // Загрузка создаёт только PDF, пакеты и BIM-модели; `other` попадает сюда же, чтобы не исчезнуть.
  return 'bim';
};

export const countByGroup = (
  documents: readonly { document_kind: DocumentKind }[],
): Record<DocumentGroup, number> =>
  documents.reduce(
    (counts, document) => {
      const group = documentGroup(document.document_kind);
      return { ...counts, [group]: counts[group] + 1 };
    },
    { pdf: 0, zip: 0, bim: 0 },
  );

export const presentGroups = (counts: Readonly<Record<DocumentGroup, number>>): DocumentGroup[] =>
  GROUP_ORDER.filter((group) => counts[group] > 0);

/**
 * Показываемая группа: выбор пользователя, пока в ней есть документы, иначе первая непустая.
 *
 * Пока пакет импортируется, PDF ещё нет — виден архив с состоянием импорта. Как только PDF
 * появится, список сам перейдёт на него, если пользователь ничего не выбирал.
 */
export const activeGroup = (
  picked: DocumentGroup | null,
  present: readonly DocumentGroup[],
): DocumentGroup | null =>
  picked !== null && present.includes(picked) ? picked : (present[0] ?? null);
