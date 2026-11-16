'use client';

import type { CadRisersCopyOut, CadRisersSheetOut } from '@quantor/api-client';
import { useId, useState, type FC } from 'react';

import { Button, Dialog, DialogActions } from '@/components/ui';
import { cadErrorText } from '@/lib/cad/errors';
import { formatFloorTitle } from '@/lib/cad/floor-title';
import { useCadPipeline } from '@/lib/cad/pipeline-queries';
import { copyResultText } from '@/lib/cad/risers';
import { sheetOf, useCadRisersSheets, useDraftCadRisersCopy } from '@/lib/cad/risers-queries';
import type { ICadViewParams } from '@/lib/cad/view-queries';

import { LABEL, SELECT } from './riser-ui';

interface ICadRisersCopyProps {
  readonly parent: ICadViewParams;
  /** В форме уже есть строки: замена требует подтверждения. */
  readonly hasRows: boolean;
  /** Сообщение о последнем копировании (хранится у родителя: форма пересоздаётся). */
  readonly message: string | null;
  readonly onCopied: (out: CadRisersCopyOut, message: string) => void;
}

const sourceKey = (sheet: Pick<CadRisersSheetOut, 'page_index' | 'view'>): string =>
  `${sheet.page_index}:${sheet.view}`;

/**
 * «Скопировать с другого листа»: сервер отдаёт черновик реестра с шахтами, перенесёнными по
 * положению; строки попадают в форму несохранёнными, сохраняет человек.
 */
export const CadRisersCopy: FC<ICadRisersCopyProps> = ({ parent, hasRows, message, onCopied }) => {
  const sheet = sheetOf(parent);
  const id = useId();
  const sheets = useCadRisersSheets(sheet.projectId, sheet.revisionId);
  const pipeline = useCadPipeline(sheet.projectId, sheet.revisionId, true);
  const draft = useDraftCadRisersCopy(sheet);
  const [selected, setSelected] = useState('');
  const [confirm, setConfirm] = useState(false);

  const sources = (sheets.data?.sheets ?? []).filter(
    (row) => !(row.page_index === sheet.pageIndex && row.view === sheet.view),
  );
  const source = sources.find((row) => sourceKey(row) === selected) ?? sources[0];
  if (!source) return null;

  const labelOf = (row: CadRisersSheetOut): string => {
    const pipelineSheet = pipeline.data?.sheets.find((item) => item.page_index === row.page_index);
    const base = formatFloorTitle(pipelineSheet?.floor_title, `Лист ${row.page_index + 1}`);
    const several = (sheets.data?.sheets ?? []).some(
      (other) => other.page_index === row.page_index && other.view !== row.view,
    );
    return several ? `${base} · вид ${row.view}` : base;
  };
  const sourceLabel = labelOf(source);

  const run = () => {
    setConfirm(false);
    draft.mutate(
      { pageIndex: source.page_index, view: source.view },
      { onSuccess: (out) => onCopied(out, copyResultText(out, sourceLabel)) },
    );
  };

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-3)]" data-testid="cad-risers-copy">
      <label className={LABEL} htmlFor={`${id}-source`}>
        Скопировать с другого листа
        <select
          id={`${id}-source`}
          value={sourceKey(source)}
          disabled={draft.isPending}
          className={SELECT}
          onChange={(event) => setSelected(event.target.value)}
        >
          {sources.map((row) => (
            <option key={sourceKey(row)} value={sourceKey(row)}>
              {labelOf(row)} ({row.risers_count})
            </option>
          ))}
        </select>
      </label>
      <Button
        loading={draft.isPending}
        disabled={draft.isPending}
        className="self-start max-md:h-[44px] max-md:w-full"
        onClick={() => (hasRows ? setConfirm(true) : run())}
      >
        Скопировать
      </Button>
      {message && (
        <p role="status" className="m-0 text-xs text-muted [overflow-wrap:anywhere]">
          {message}
        </p>
      )}
      {draft.isError && (
        <p role="alert" className="m-0 text-xs text-danger [overflow-wrap:anywhere]">
          {cadErrorText(draft.error)}
        </p>
      )}
      <Dialog
        open={confirm}
        onClose={() => setConfirm(false)}
        title="Заменить строки формы?"
        description={`Строки формы заменятся строками листа ${sourceLabel}; реестр не сохранится, пока вы не нажмёте «Сохранить».`}
        footer={
          <DialogActions>
            <Button onClick={() => setConfirm(false)}>Отмена</Button>
            <Button variant="primary" onClick={run}>
              Заменить
            </Button>
          </DialogActions>
        }
      >
        <p className="m-0 text-sm text-muted">Несохранённые правки формы будут потеряны.</p>
      </Dialog>
    </div>
  );
};
