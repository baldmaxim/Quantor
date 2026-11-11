'use client';

import type { CadVorCoverageGroupRead } from '@quantor/api-client';
import { useState, type FC } from 'react';

import { Button, Dialog, DialogActions } from '@/components/ui';
import {
  thicknessListText,
  thicknessesOfKeys,
  vorGroupLabel,
  vorItemQuantity,
  vorItemTitle,
} from '@/lib/cad/vor';

import type { IWorkspaceCadVor } from './types';
import { VorLinkDialog } from './VorLinkDialog';
import { VorSourcePicker } from './VorSourcePicker';

interface IConstructionsVorProps {
  vor: IWorkspaceCadVor;
}

const HEADING = 'text-micro font-semibold tracking-[0.06em] text-muted uppercase';

const formatDate = (iso: string): string => {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleDateString('ru-RU');
};

interface IGroupRowProps {
  group: CadVorCoverageGroupRead;
  onMatch: (group: CadVorCoverageGroupRead) => void;
}

/** Группа свода и её статус в ВОР. Количества ВОР - справочно, с количествами CAD не сравниваются. */
const GroupRow: FC<IGroupRowProps> = ({ group, onMatch }) => (
  <li
    data-testid="vor-group"
    data-status={group.status}
    className="flex min-w-0 flex-col gap-[var(--s-2)] border-t border-border py-[var(--s-3)] first:border-t-0"
  >
    <div className="flex min-w-0 flex-wrap items-center justify-between gap-[var(--s-3)]">
      <span className="min-w-0 text-xs font-medium [overflow-wrap:anywhere]">{vorGroupLabel(group)}</span>
      <span className="flex items-center gap-[var(--s-3)]">
        {group.status === 'linked' ? (
          <span className="text-xs text-muted">в ВОР</span>
        ) : (
          <span className="text-xs font-semibold text-danger">не в ВОР</span>
        )}
        <Button compact className="max-md:h-[44px]" onClick={() => onMatch(group)}>
          Сопоставить
        </Button>
      </span>
    </div>
    {group.items.length > 0 && (
      <ul className="m-0 flex list-none flex-col gap-[var(--s-2)] p-0">
        {group.items.map((item) => (
          <li key={item.id} className="text-xs text-muted [overflow-wrap:anywhere]">
            <span className="text-text">{vorItemTitle(item)}</span>
            {' · '}
            {vorItemQuantity(item)} (по ВОР, на весь объект)
          </li>
        ))}
      </ul>
    )}
  </li>
);

/**
 * Блок «ВОР Заказчика» раздела «Конструкции» (ADR-0038 п. 5): выбор книги из документов проекта,
 * статус каждой группы свода в ВОР, сопоставление с его строками, толщины ВОР. ВОР - только объект
 * сверки: количества ВОР показываются справочно, на расчёт не влияют и с количествами CAD не
 * сравниваются.
 */
export const ConstructionsVor: FC<IConstructionsVorProps> = ({ vor }) => {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [matching, setMatching] = useState<CadVorCoverageGroupRead | null>(null);

  const { document, coverage } = vor;
  const busy = vor.importing || vor.deleting;

  const picker = (
    <VorSourcePicker
      projectId={vor.projectId}
      sources={vor.sources}
      loading={vor.sourcesLoading}
      currentSha256={document?.sha256 ?? null}
      disabled={busy}
      onPick={vor.onImport}
    />
  );

  const error = vor.error;
  const missing = coverage?.thickness_not_in_vor ?? [];
  const missingThicknesses = thicknessesOfKeys(missing);

  return (
    <section aria-label="ВОР Заказчика" className="flex min-w-0 flex-col gap-[var(--s-3)]">
      <h4 className={HEADING}>ВОР Заказчика</h4>
      {error !== null && (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      )}
      {vor.importing && (
        <p role="status" className="text-xs text-muted">
          ВОР берётся из документа и разбирается…
        </p>
      )}

      {document === null ? (
        vor.loading ? (
          <p role="status" className="text-xs text-muted">
            Загрузка ВОР…
          </p>
        ) : (
          <>
            <p className="text-xs text-muted">ВОР — только для сверки, на расчёт не влияет.</p>
            {picker}
          </>
        )
      ) : (
        <>
          <p className="text-xs [overflow-wrap:anywhere]">
            <span className="text-text">{document.file_name}</span>
            <span className="text-muted">
              {' '}
              · строк: {document.rows_count} · загружен {formatDate(document.created_at)}
            </span>
          </p>
          <p className="text-xs text-muted">
            ВОР — только для сверки, на расчёт не влияет. Выбор другой книги сбрасывает сопоставления.
          </p>
          {picker}
          <div className="flex flex-wrap gap-[var(--s-3)]">
            <Button
              variant="danger"
              disabled={busy}
              className="max-md:h-[44px]"
              onClick={() => setConfirmDelete(true)}
            >
              Удалить
            </Button>
          </div>

          {coverage?.has_vor === true && (
            <>
              <label className="flex min-h-[44px] items-center gap-[var(--s-3)] text-xs md:min-h-[32px]">
                <input
                  type="checkbox"
                  checked={vor.showNotInVor}
                  onChange={(event) => vor.onShowNotInVorChange(event.target.checked)}
                  className="size-5 shrink-0"
                />
                <span
                  aria-hidden="true"
                  className="size-3 shrink-0 border-2 border-dashed border-[var(--cad-construction-not-in-vor)]"
                />
                Не в ВОР
              </label>
              {coverage.groups.length === 0 ? (
                <p className="text-xs text-muted">Посчитанных групп на листе нет: сверять нечего.</p>
              ) : (
                <ul aria-label="Группы и ВОР" className="m-0 flex list-none flex-col p-0">
                  {coverage.groups.map((group) => (
                    <GroupRow key={group.group_key} group={group} onMatch={setMatching} />
                  ))}
                </ul>
              )}
              {missingThicknesses.length > 0 && (
                <p className="text-xs text-danger">
                  Толщины, которых нет в ВОР: {thicknessListText(missingThicknesses)}
                </p>
              )}
              {coverage.vor_thicknesses.length > 0 && (
                <p className="text-xs text-muted">
                  Толщины в ВОР: {thicknessListText(coverage.vor_thicknesses)}
                </p>
              )}
            </>
          )}
        </>
      )}

      {matching !== null && document !== null && (
        <VorLinkDialog
          // Состав выбора принадлежит группе и документу.
          key={`${document.id}:${matching.group_key}`}
          projectId={vor.projectId}
          documentId={document.id}
          group={matching}
          onClose={() => setMatching(null)}
        />
      )}

      <Dialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title="Удалить ВОР Заказчика?"
        description="Строки ВОР и сопоставления групп будут удалены. Конструкции и расчёт не меняются."
        footer={
          <DialogActions>
            <Button onClick={() => setConfirmDelete(false)}>Отмена</Button>
            <Button
              variant="danger"
              onClick={() => {
                setConfirmDelete(false);
                vor.onDelete();
              }}
            >
              Удалить
            </Button>
          </DialogActions>
        }
      >
        <p className="text-sm">{document?.file_name}</p>
      </Dialog>
    </section>
  );
};
