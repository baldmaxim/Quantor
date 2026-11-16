'use client';

import type { TenderBaseCandidateRead } from '@quantor/api-client';
import { useMemo, useState, type FC } from 'react';

import {
  Button,
  Dialog,
  DialogActions,
  ErrorState,
  SkeletonRows,
  StatusBadge,
} from '@/components/ui';
import { ClearableInput } from '@/components/ui/ClearableInput';
import { errorMessage, extractCode, extractMessage } from '@/lib/errors';
import { defaultSelection, groupCandidates } from '@/lib/tender/candidates';
import { useCreateTenderBaseRelease, useTenderBaseCandidates } from '@/lib/tender/queries';

import { CandidateTree } from './CandidateTree';

/**
 * Окно «Выпустить базу»: этажи здания деревом корпус → секция → этаж с флажками (по умолчанию готовые
 * и совмещённые по осям), «С DXF планов», комментарий. Успех закрывает окно: новый выпуск уже в списке.
 */

interface IDialogProps {
  readonly projectId: string;
  readonly open: boolean;
  readonly onClose: () => void;
}

export const BaseReleaseDialog: FC<IDialogProps> = ({ projectId, open, onClose }) => {
  const candidates = useTenderBaseCandidates(projectId, open);
  const create = useCreateTenderBaseRelease(projectId);
  // Ручные отметки поверх отметок по умолчанию: состояние выводится, а не копируется эффектом.
  const [overrides, setOverrides] = useState<Readonly<Record<string, boolean>>>({});
  const [includeDxf, setIncludeDxf] = useState(false);
  const [comment, setComment] = useState('');

  const list: readonly TenderBaseCandidateRead[] = useMemo(
    () => candidates.data?.candidates ?? [],
    [candidates.data],
  );
  const groups = useMemo(() => groupCandidates(list), [list]);
  const selected: ReadonlySet<string> = useMemo(() => {
    const result = new Set(defaultSelection(list));
    for (const [key, on] of Object.entries(overrides)) {
      if (on) result.add(key);
      else result.delete(key);
    }
    return result;
  }, [list, overrides]);

  const toggle = (keys: readonly string[], on: boolean): void =>
    setOverrides((current) => ({
      ...current,
      ...Object.fromEntries(keys.map((key) => [key, on])),
    }));

  const busy = create.isPending;
  const submit = (): void =>
    create.mutate(
      { view_keys: [...selected], include_dxf: includeDxf, comment: comment.trim() },
      { onSuccess: onClose },
    );

  return (
    <Dialog
      open={open}
      onClose={onClose}
      busy={busy}
      size="lg"
      title="Выпустить базу объекта"
      description="Выпуск неизменяем: в него войдёт состояние выбранных этажей на сейчас."
      onExited={() => {
        create.reset();
        setOverrides({});
        setComment('');
        setIncludeDxf(false);
      }}
      footer={
        <DialogActions>
          <Button onClick={onClose} disabled={busy}>
            Отмена
          </Button>
          <Button variant="primary" onClick={submit} disabled={busy || selected.size === 0}>
            {busy ? 'Выпускаем…' : `Выпустить (${selected.size})`}
          </Button>
        </DialogActions>
      }
    >
      {candidates.isPending && <SkeletonRows rows={5} />}
      {candidates.isError && (
        <ErrorState
          title="Этажи не загрузились"
          code={extractCode(candidates.error)}
          description={
            extractMessage(candidates.error) ?? errorMessage(extractCode(candidates.error))
          }
          onRetry={() => void candidates.refetch()}
        />
      )}
      {candidates.data && (
        <>
          {candidates.data.warnings.length > 0 && (
            <ul className="m-0 flex list-none flex-col gap-[var(--s-2)] p-0">
              {candidates.data.warnings.map((warning) => (
                <li key={warning} className="flex items-start gap-[var(--s-3)] text-sm">
                  <StatusBadge tone="warning">внимание</StatusBadge>
                  <span>{warning}</span>
                </li>
              ))}
            </ul>
          )}
          {list.length === 0 ? (
            <p className="m-0 text-sm text-muted">
              В здании проекта нет этажей для выпуска: сначала постройте план листов в CAD.
            </p>
          ) : (
            <CandidateTree groups={groups} selected={selected} onToggle={toggle} />
          )}
          <label className="inline-flex min-h-[44px] cursor-pointer items-center gap-[var(--s-4)] text-sm md:min-h-[var(--h-ctl)]">
            <input
              type="checkbox"
              checked={includeDxf}
              onChange={(event) => setIncludeDxf(event.target.checked)}
              className="h-[16px] w-[16px] accent-[var(--accent)]"
            />
            С DXF планов
          </label>
          <ClearableInput
            label="Комментарий"
            placeholder="Комментарий к выпуску"
            value={comment}
            maxLength={500}
            onChange={(event) => setComment(event.target.value)}
            onClear={() => setComment('')}
            wrapperClassName="flex w-full"
          />
          {create.isError && (
            <p role="alert" className="m-0 text-sm text-danger">
              {extractMessage(create.error) ?? errorMessage(extractCode(create.error))}
            </p>
          )}
        </>
      )}
    </Dialog>
  );
};
