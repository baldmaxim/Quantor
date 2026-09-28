'use client';

import type { CalcFactTypeRead } from '@quantor/api-client';
import { useMemo, useState } from 'react';

import { DocumentsPanel } from '@/components/calc/DocumentsPanel';
import { InputFactsTable } from '@/components/calc/InputFactsTable';
import { ReadinessMatrix } from '@/components/calc/ReadinessMatrix';
import { Button, EmptyState, ErrorState, SegmentedControl, SkeletonRows } from '@/components/ui';
import {
  useCalcDocuments,
  useCalcFactTypes,
  useCalcInputFacts,
  useCalcReadiness,
} from '@/lib/calc/queries';

/**
 * Экран «Расчёты → Исходные данные»: что известно для будущего расчёта и чего не хватает.
 *
 * Расчёта здесь нет: сервер отдаёт готовность, факты и документы, экран их только показывает.
 */

type Section = 'readiness' | 'facts' | 'documents';

const PAGE = 200;
const LIMIT = 500;

export const CalcInputs = ({ projectId }: { projectId: string }) => {
  const [section, setSection] = useState<Section>('readiness');
  const [limit, setLimit] = useState(PAGE);

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
          <ReadinessMatrix readiness={readiness.data} factTypes={types} />
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
            <InputFactsTable items={facts.data.items} factTypes={types} />
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
    </div>
  );
};
