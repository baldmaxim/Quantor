'use client';

import type { DocumentRead, DocumentRevisionRead } from '@quantor/api-client';
import { useMemo, useState, type FC } from 'react';

import { cx } from '@/components/ui';
import { IconChevronRight } from '@/components/ui/icons';
import { groupDocuments, type SectionId } from '@/lib/documentSections';

import { DocumentRow } from './DocumentRow';

/**
 * Документы проекта по разделам проектной документации.
 *
 * Раздел определяется по шифру в имени файла (`lib/documentSections`), у PDF отмечен
 * распознанный пакет того же имени. Клик по строке выбирает документ (`onSelect`). Группы
 * сворачиваются; свёрнутые разделы помнятся в localStorage на проект. Хранилище может быть недоступно — тогда выбор живёт до
 * закрытия вкладки.
 */

export interface IRevisionsInfo {
  readonly items: readonly DocumentRevisionRead[];
  readonly total: number;
}

export interface IDocumentSectionsProps {
  readonly projectId: string;
  readonly documents: readonly DocumentRead[];
  /** `undefined`/`null`, пока ревизии документа не загружены. */
  readonly revisionsOf: (documentId: string) => IRevisionsInfo | null | undefined;
  /** Выбранный документ: его обработка показана рядом со списком. */
  readonly selectedId?: string | null;
  readonly onSelect?: (documentId: string) => void;
}

export const collapsedKey = (projectId: string): string =>
  `quantor.documentSections.collapsed.${projectId}`;

const readCollapsed = (projectId: string): ReadonlySet<SectionId> => {
  try {
    const raw = window.localStorage.getItem(collapsedKey(projectId));
    const parsed: unknown = raw === null ? [] : JSON.parse(raw);
    return new Set(
      Array.isArray(parsed)
        ? parsed.filter((value): value is SectionId => typeof value === 'string')
        : [],
    );
  } catch {
    return new Set();
  }
};

const writeCollapsed = (projectId: string, collapsed: ReadonlySet<SectionId>): void => {
  try {
    window.localStorage.setItem(collapsedKey(projectId), JSON.stringify([...collapsed]));
  } catch {
    // хранилище недоступно — состояние остаётся только в памяти вкладки
  }
};

export const DocumentSections: FC<IDocumentSectionsProps> = ({
  projectId,
  documents,
  revisionsOf,
  selectedId = null,
  onSelect,
}) => {
  const groups = useMemo(() => groupDocuments(documents), [documents]);
  const [collapsed, setCollapsed] = useState<ReadonlySet<SectionId>>(() =>
    readCollapsed(projectId),
  );

  const toggle = (id: SectionId): void => {
    const next = new Set(collapsed);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setCollapsed(next);
    writeCollapsed(projectId, next);
  };

  return (
    <>
      {groups.map((group) => {
        const open = !collapsed.has(group.id);
        const bodyId = `document-section-${group.id}`;

        return (
          <section
            key={group.id}
            aria-label={group.title}
            className="border-b border-border last:border-b-0"
          >
            <h3 className="m-0">
              <button
                type="button"
                aria-expanded={open}
                aria-controls={bodyId}
                onClick={() => toggle(group.id)}
                className="flex min-h-[44px] w-full cursor-pointer items-center gap-[var(--s-4)] py-[var(--s-3)] text-left text-sm font-medium [-webkit-tap-highlight-color:transparent] [touch-action:manipulation]"
              >
                <IconChevronRight className={cx('flex-none text-muted', open && 'rotate-90')} />
                <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">{group.title}</span>
                <span className="mono flex-none text-xs font-normal text-muted">
                  {group.entries.length}
                </span>
              </button>
            </h3>

            {open && (
              <div id={bodyId}>
                {group.entries.map(({ document, packages }) => {
                  const info = revisionsOf(document.id);
                  return (
                    <DocumentRow
                      key={document.id}
                      projectId={projectId}
                      document={document}
                      revisions={info?.items ?? null}
                      total={info?.total ?? 0}
                      packageCount={packages.length}
                      selected={document.id === selectedId}
                      onSelect={onSelect}
                    />
                  );
                })}
              </div>
            )}
          </section>
        );
      })}
    </>
  );
};
