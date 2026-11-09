'use client';

import type { FC } from 'react';

import { Button, InspectorSection, cx } from '@/components/ui';
import {
  cameraForBbox,
  remarksCounter,
  type BboxPt,
  type IPageSizePt,
  type IRemarkBinding,
} from '@/lib/cad/remarks';
import type { CameraState, Viewport } from '@/lib/viewer/camera';

import { CadRemarkEditor } from './CadRemarkEditor';
import { CadRemarkItem } from './CadRemarkItem';
import { CadRemarksIo } from './CadRemarksIo';
import type { ICadRemarks, IRemarkDraft } from './useCadRemarks';

interface ICadRemarksPanelProps {
  binding: IRemarkBinding;
  store: ICadRemarks;
  page: IPageSizePt | null;
  /** Режим «Отметить участок» включён. */
  marking: boolean;
  onMarkingChange: (value: boolean) => void;
  /** Почему отметка недоступна; `null` - доступна. */
  markDisabledReason: string | null;
  /** Участок, нарисованный и ещё не сохранённый. */
  draft: BboxPt | null;
  onDraftSave: (draft: IRemarkDraft) => void;
  onDraftCancel: () => void;
  activeId: string | null;
  onActivate: (id: string | null) => void;
  /** Состояние камеры по прямоугольнику; `null` - «К участку» недоступно (листа или области нет). */
  onFocusCamera: ((state: CameraState) => void) | null;
  viewport: () => Viewport;
}

/** Раздел «Замечания» панели вида: отметка участка, список, обмен JSON. */
export const CadRemarksPanel: FC<ICadRemarksPanelProps> = ({
  binding,
  store,
  page,
  marking,
  onMarkingChange,
  markDisabledReason,
  draft,
  onDraftSave,
  onDraftCancel,
  activeId,
  onActivate,
  onFocusCamera,
  viewport,
}) => {
  const { remarks } = store;

  return (
    <InspectorSection
      title="Замечания"
      aside={
        <span className="tabular text-xs font-normal tracking-normal text-muted normal-case">
          {store.loading ? '…' : remarksCounter(remarks)}
        </span>
      }
    >
      <div className="flex min-w-0 flex-col gap-[var(--s-5)]" data-testid="cad-remarks">
        <p className="rounded-[var(--radius-sm)] border border-warning-soft bg-warning-soft px-[var(--s-4)] py-[var(--s-3)] text-xs">
          Замечания хранятся на сервере и видны всем, у кого есть доступ к этой ревизии; для
          передачи вне портала — экспорт JSON. Это не инженерная приёмка.
        </p>
        {store.loadError && (
          <div
            role="alert"
            className="flex flex-wrap items-center gap-[var(--s-3)] text-xs text-danger"
          >
            <span>Не удалось загрузить замечания. {store.loadError}</span>
            <Button compact onClick={store.reload} className="max-md:h-[44px]">
              Повторить
            </Button>
          </div>
        )}
        {store.error && (
          <p role="alert" className="text-xs text-danger">
            {store.error}
          </p>
        )}

        <div className="flex min-w-0 flex-col gap-[var(--s-3)]">
          <Button
            variant={marking ? 'primary' : 'default'}
            aria-pressed={marking}
            disabled={markDisabledReason !== null}
            onClick={() => onMarkingChange(!marking)}
            className="self-start max-md:w-full"
          >
            {marking ? 'Отмечаю: протяните прямоугольник' : 'Отметить участок'}
          </Button>
          {markDisabledReason && (
            <p className="text-xs text-muted" role="note">
              {markDisabledReason}
            </p>
          )}
        </div>

        {draft && (
          <CadRemarkEditor
            number={remarks.length + 1}
            saving={store.saving}
            onSave={onDraftSave}
            onCancel={onDraftCancel}
          />
        )}

        {store.loading ? (
          <p role="status" className="text-xs text-muted">
            Загрузка замечаний…
          </p>
        ) : remarks.length === 0 ? (
          <p className="text-xs text-muted">Замечаний к этому виду нет.</p>
        ) : (
          <ul
            aria-label="Замечания к виду"
            className={cx(
              'scroll-area flex max-h-[320px] flex-col overflow-auto overscroll-contain rounded-[var(--radius-md)] border border-border',
            )}
          >
            {remarks.map((remark, index) => (
              <CadRemarkItem
                key={remark.id}
                number={index + 1}
                remark={remark}
                active={remark.id === activeId}
                onActivate={() => onActivate(remark.id === activeId ? null : remark.id)}
                onStatusChange={(status) => store.update(remark.id, { status })}
                onFocus={
                  onFocusCamera
                    ? () => {
                        onActivate(remark.id);
                        const state = cameraForBbox(remark.bbox_pt, viewport());
                        if (state) onFocusCamera(state);
                      }
                    : null
                }
                onDelete={() => {
                  if (remark.id === activeId) onActivate(null);
                  store.remove(remark.id);
                }}
              />
            ))}
          </ul>
        )}

        <CadRemarksIo
          binding={binding}
          page={page}
          remarks={remarks}
          reviewer={store.reviewer}
          onReviewerChange={store.setReviewer}
          onImport={store.importFile}
        />
      </div>
    </InspectorSection>
  );
};
