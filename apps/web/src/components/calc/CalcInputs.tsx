'use client';

import type { CalcFactRead, CalcFactTypeRead } from '@quantor/api-client';
import { useMemo, useState } from 'react';

import { DocumentsPanel } from '@/components/calc/DocumentsPanel';
import {
  ConflictDialog,
  FactActionDialog,
  type ConflictTarget,
  type FactAction,
} from '@/components/calc/FactDecisionDialogs';
import { InputFactsTable } from '@/components/calc/InputFactsTable';
import { ManualFactDialog, type IManualTarget } from '@/components/calc/ManualFactDialog';
import { ReadinessMatrix } from '@/components/calc/ReadinessMatrix';
import { Button, EmptyState, ErrorState, SegmentedControl, SkeletonRows } from '@/components/ui';
import {
  useCalcDocuments,
  useCalcFactTypes,
  useCalcInputFacts,
  useCalcReadiness,
} from '@/lib/calc/queries';
import { useHasPermission, useSession } from '@/lib/session';

/**
 * Экран «Расчёты → Исходные данные»: что известно для будущего расчёта и чего не хватает.
 *
 * Расчёта здесь нет: сервер отдаёт готовность, факты и документы. Человек работает только с
 * недостающим и спорным: вводит значение с основанием (последний путь), решает конфликт
 * источников, подтверждает или отклоняет утверждение — всё через реестр фактов (PROMPT 01).
 */

type Section = 'readiness' | 'facts' | 'documents';

const PAGE = 200;
const LIMIT = 500;

export const CalcInputs = ({ projectId }: { projectId: string }) => {
  const [section, setSection] = useState<Section>('readiness');
  const [limit, setLimit] = useState(PAGE);
  const [manual, setManual] = useState<IManualTarget | null>(null);
  const [conflict, setConflict] = useState<ConflictTarget | null>(null);
  const [factAction, setFactAction] = useState<{ action: FactAction; fact: CalcFactRead } | null>(
    null,
  );
  const canEdit = useHasPermission('calc.edit');
  const canVerify = useHasPermission('calc.verify');
  const userId = useSession().data?.user?.id ?? undefined;

  const factTypes = useCalcFactTypes(true);
  const readiness = useCalcReadiness(projectId, section === 'readiness');
  const facts = useCalcInputFacts(projectId, section === 'facts', limit);
  const documents = useCalcDocuments(projectId, section === 'documents');

  const types = useMemo(
    () => new Map<string, CalcFactTypeRead>((factTypes.data ?? []).map((item) => [item.key, item])),
    [factTypes.data],
  );

  return (
    <div className="flex flex-col gap-[var(--s-5)]">
      <SegmentedControl
        label="Раздел"
        value={section}
        onChange={setSection}
        options={[
          { value: 'readiness', label: 'Готовность к расчёту' },
          { value: 'facts', label: 'Факты' },
          { value: 'documents', label: 'Документы' },
        ]}
      />

      {section === 'readiness' &&
        (readiness.isError ? (
          <ErrorState title="Готовность не загрузилась" onRetry={() => void readiness.refetch()} />
        ) : readiness.data ? (
          <ReadinessMatrix
            readiness={readiness.data}
            factTypes={types}
            onEnter={
              canEdit
                ? (row, system) => {
                    const type = types.get(row.fact_type);
                    if (type) {
                      setManual({
                        type,
                        title: `${row.title} — ${system.system_code}`,
                        discipline: system.discipline,
                        systemCode: system.system_code,
                        assumptionAllowed: row.assumption === 'MANUAL',
                      });
                    }
                  }
                : undefined
            }
            onResolve={(conflictId) => setConflict({ conflictId })}
          />
        ) : (
          <SkeletonRows rows={6} />
        ))}

      {section === 'facts' &&
        (facts.isError ? (
          <ErrorState title="Факты не загрузились" onRetry={() => void facts.refetch()} />
        ) : !facts.data ? (
          <SkeletonRows rows={6} />
        ) : facts.data.items.length === 0 ? (
          <EmptyState
            compact
            title="Фактов пока нет"
            description="Соберите факты из распознанных документов в разделе «Документы»."
          />
        ) : (
          <>
            <InputFactsTable
              items={facts.data.items}
              factTypes={types}
              projectId={projectId}
              canVerify={canVerify}
              canEdit={canEdit}
              currentUserId={userId}
              onAction={(action, fact) => setFactAction({ action, fact })}
              onConflict={(fact) => setConflict({ factKey: fact.fact_key })}
            />
            {facts.data.total > facts.data.items.length &&
              (limit < LIMIT ? (
                <Button onClick={() => setLimit((current) => Math.min(current + PAGE, LIMIT))}>
                  Показать ещё
                </Button>
              ) : (
                <p className="text-xs text-muted">
                  Показаны первые {facts.data.items.length} из {facts.data.total}.
                </p>
              ))}
          </>
        ))}

      {section === 'documents' &&
        (documents.isError ? (
          <ErrorState title="Документы не загрузились" onRetry={() => void documents.refetch()} />
        ) : !documents.data ? (
          <SkeletonRows rows={4} />
        ) : documents.data.length === 0 ? (
          <EmptyState
            compact
            title="Документов нет"
            description="Загрузите распознанный пакет на карточке проекта."
          />
        ) : (
          <DocumentsPanel projectId={projectId} documents={documents.data} />
        ))}

      <ManualFactDialog projectId={projectId} target={manual} onClose={() => setManual(null)} />
      <ConflictDialog
        projectId={projectId}
        target={conflict}
        canDecide={canVerify}
        factTypes={types}
        onClose={() => setConflict(null)}
      />
      <FactActionDialog
        projectId={projectId}
        target={factAction}
        factTypes={types}
        onClose={() => setFactAction(null)}
      />
    </div>
  );
};
