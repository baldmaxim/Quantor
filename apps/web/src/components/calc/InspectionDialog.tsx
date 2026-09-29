'use client';

import type {
  CalcCollectableDocumentRead,
  CalcDiscipline,
  CalcDocumentStage,
  CalcInspectionRead,
  CalcSourceClass,
} from '@quantor/api-client';
import { useId, useState } from 'react';

import { Button, Dialog, DialogActions, ErrorState, SegmentedControl } from '@/components/ui';
import {
  DISCIPLINE_TITLES,
  DOCUMENT_CLASSES,
  SOURCE_CLASS_TITLES,
  STAGE_TITLES,
  TABLE_KIND_TITLES,
} from '@/lib/calc/format';
import { useStartInspection } from '@/lib/calc/queries';
import { errorMessage, extractCode } from '@/lib/errors';

/**
 * Заявление документа и сбор фактов.
 *
 * Имя файла доказательством не считается: что это за документ, какой стадии и какого корпуса,
 * заявляет человек. Штамп подсказывает раздел и стадию — подсказка видна, но решение за
 * человеком; расхождение со штампом сервер запишет в сводку сбора.
 */

const FIELD =
  'h-[var(--h-ctl)] rounded-[var(--radius-sm)] border border-border-control bg-surface px-[var(--s-5)] text-sm text-text disabled:opacity-60';
const STAGES: readonly CalcDocumentStage[] = ['P', 'RD', 'UNKNOWN'];
const DISCIPLINES: readonly CalcDiscipline[] = ['VK', 'OV', 'EOM', 'SS'];

interface IInspectionDialogProps {
  projectId: string;
  document: CalcCollectableDocumentRead | null;
  onClose: () => void;
}

export const InspectionDialog = ({ projectId, document, onClose }: IInspectionDialogProps) => (
  <Dialog
    open={document !== null}
    onClose={onClose}
    title="Собрать факты из документа"
    description={document?.title}
    size="lg"
  >
    {document && (
      <InspectionForm
        key={document.document_revision_id}
        projectId={projectId}
        document={document}
        onClose={onClose}
      />
    )}
  </Dialog>
);

const InspectionForm = ({
  projectId,
  document,
  onClose,
}: {
  projectId: string;
  document: CalcCollectableDocumentRead;
  onClose: () => void;
}) => {
  const last = document.last_inspection;
  const [sourceClass, setSourceClass] = useState<CalcSourceClass | ''>(
    last?.source_class ?? document.suggested_class ?? '',
  );
  const [stage, setStage] = useState<CalcDocumentStage>(
    last?.document_stage ?? document.stamp_stage ?? 'UNKNOWN',
  );
  const [building, setBuilding] = useState(last?.building ?? '');
  const [discipline, setDiscipline] = useState<CalcDiscipline | ''>(
    last?.discipline ?? document.suggested_discipline ?? '',
  );
  const classId = useId();
  const buildingId = useId();
  const disciplineId = useId();
  const mutation = useStartInspection(projectId);

  const mep = sourceClass === 'MEP_DESIGN';
  const buildingIsList = /\d\s*[,;]\s*\d/.test(building);
  const ready =
    sourceClass !== '' && building.trim().length > 0 && !buildingIsList && (!mep || discipline !== '');

  if (mutation.data) {
    return <InspectionResult inspection={mutation.data} onClose={onClose} />;
  }

  const submit = () => {
    if (sourceClass === '') return;
    mutation.mutate({
      document_revision_id: document.document_revision_id,
      source_class: sourceClass,
      document_stage: stage,
      building: building.trim(),
      discipline: mep && discipline !== '' ? discipline : null,
    });
  };

  return (
    <div className="flex flex-col gap-[var(--s-5)]">
      {(document.stamp_section || document.stamp_stage) && (
        <p className="text-sm text-muted">
          По штампу: {document.stamp_section ?? 'раздел не определён'}, стадия{' '}
          {document.stamp_stage ? STAGE_TITLES[document.stamp_stage] : 'не определена'}.
        </p>
      )}

      <label htmlFor={classId} className="flex flex-col gap-[var(--s-3)]">
        <span className="text-sm">Что это за документ</span>
        <select
          id={classId}
          value={sourceClass}
          onChange={(event) => setSourceClass(event.target.value as CalcSourceClass | '')}
          className={FIELD}
        >
          <option value="">— выберите —</option>
          {DOCUMENT_CLASSES.map((item) => (
            <option key={item} value={item}>
              {SOURCE_CLASS_TITLES[item]}
            </option>
          ))}
        </select>
      </label>

      <div className="flex flex-col gap-[var(--s-3)]">
        <span className="text-sm">Стадия документа</span>
        <SegmentedControl
          label="Стадия документа"
          value={stage}
          onChange={setStage}
          options={STAGES.map((item) => ({ value: item, label: STAGE_TITLES[item] }))}
        />
      </div>

      <label htmlFor={buildingId} className="flex flex-col gap-[var(--s-3)]">
        <span className="text-sm">Корпус, к которому относится документ</span>
        <input
          id={buildingId}
          value={building}
          onChange={(event) => setBuilding(event.target.value)}
          placeholder="Например: 1"
          maxLength={64}
          className={FIELD}
        />
        <span className="text-xs text-muted">
          Укажите один корпус. Для корпуса 1 с секциями 1, 2 и 3 введите «1».
        </span>
        {buildingIsList && (
          <span className="text-xs text-danger">Нельзя перечислить несколько корпусов.</span>
        )}
      </label>

      {mep && (
        <label htmlFor={disciplineId} className="flex flex-col gap-[var(--s-3)]">
          <span className="text-sm">Раздел</span>
          <select
            id={disciplineId}
            value={discipline}
            onChange={(event) => setDiscipline(event.target.value as CalcDiscipline | '')}
            className={FIELD}
          >
            <option value="">— выберите —</option>
            {DISCIPLINES.map((item) => (
              <option key={item} value={item}>
                {DISCIPLINE_TITLES[item]}
              </option>
            ))}
          </select>
        </label>
      )}

      {sourceClass === 'CUSTOMER_VOR' && (
        <p className="text-sm text-warning">
          Из ВОР Заказчика берутся только упоминания систем — для сверки. Количества, диаметры и
          решения ВОР в реестр не попадают и в расчёт не идут.
        </p>
      )}

      {mutation.isError && (
        <ErrorState
          title="Сбор не выполнен"
          code={extractCode(mutation.error)}
          description={errorMessage(extractCode(mutation.error))}
        />
      )}

      <DialogActions>
        <Button onClick={onClose} disabled={mutation.isPending}>
          Отмена
        </Button>
        <Button
          variant="primary"
          onClick={submit}
          disabled={!ready || mutation.isPending}
          loading={mutation.isPending}
          loadingLabel="Собираем…"
        >
          Собрать факты
        </Button>
      </DialogActions>
    </div>
  );
};

const InspectionResult = ({
  inspection,
  onClose,
}: {
  inspection: CalcInspectionRead;
  onClose: () => void;
}) => {
  const summary = inspection.summary;
  return (
    <div className="flex flex-col gap-[var(--s-5)] text-sm">
      <p>
        Принято значений: {summary.accepted}. Новых утверждений: {summary.created}, без изменений:{' '}
        {summary.unchanged}, заменено: {summary.superseded}, отозвано: {summary.withdrawn}.
      </p>
      <p className="text-muted">
        Таблиц: {summary.tables_total}
        {summary.tables.length > 0 &&
          ` (${summary.tables
            .map((item) => `${TABLE_KIND_TITLES[item.kind]} — ${item.count}`)
            .join(', ')})`}
        .
      </p>
      {summary.issues.length > 0 && (
        <div className="flex flex-col gap-[var(--s-2)]">
          <span className="font-medium">Не взято и почему</span>
          <ul className="flex list-disc flex-col gap-[var(--s-2)] pl-[var(--s-6)] text-muted">
            {summary.issues.slice(0, 6).map((issue) => (
              <li
                key={`${issue.code}-${issue.fact_type}-${issue.message}`}
                className="wrap-anywhere"
              >
                {issue.message}
                {issue.count > 1 && ` — ${issue.count}`}
              </li>
            ))}
          </ul>
        </div>
      )}
      {summary.limitations.map((note) => (
        <p key={note} className="text-xs text-muted">
          {note}
        </p>
      ))}
      <DialogActions>
        <Button variant="primary" onClick={onClose}>
          Готово
        </Button>
      </DialogActions>
    </div>
  );
};
