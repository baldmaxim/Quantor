'use client';

import type { ModelPartRead } from '@quantor/api-client';
import { useMemo, useState, type FC } from 'react';

import { Button, EmptyState, ErrorState, SkeletonRows, StatusBadge } from '@/components/ui';
import { extractCode } from '@/lib/errors';
import {
  elementTitle,
  formatElevation,
  propertyRows,
  type IModelElement,
} from '@/lib/model/model-elements';
import {
  useApproveModelVersion,
  useModelVersion,
  useModelVersions,
  useStoreyElements,
  useStoreyGeometry,
} from '@/lib/model/model-queries';
import type { IModelPartInput } from '@/lib/model/model-scene';
import { MODEL_STATUS, pickVersion } from '@/lib/model/model-versions';

import { ModelImportPanel } from './ModelImportPanel';
import { ModelSpeckleCanvas } from './ModelSpeckleCanvas';
import { ModelViewerCanvas } from './ModelViewerCanvas';

interface IModelScreenProps {
  readonly projectId: string;
}

const geometryOf = (parts: readonly ModelPartRead[], storeyKey: string): ModelPartRead[] =>
  parts.filter((part) => part.kind === 'geometry' && part.storey_key === storeyKey);

const SIDE = 'flex min-h-0 min-w-0 flex-col gap-[var(--s-4)] overflow-y-auto p-[var(--s-4)]';

/**
 * «Модель здания»: версии пакета QMP проекта, этажи, 3D выбранного этажа по дисциплинам и
 * свойства элемента по щелчку. Версия - кандидат, пока её не утвердил человек.
 */
export const ModelScreen: FC<IModelScreenProps> = ({ projectId }) => {
  const versions = useModelVersions(projectId, true);
  const [chosen, setChosen] = useState<string | null>(null);
  const items = versions.data?.items ?? [];
  const versionId = chosen ?? pickVersion(items);
  const detail = useModelVersion(projectId, versionId);
  const approve = useApproveModelVersion(projectId);

  const [storeyChoice, setStoreyChoice] = useState<string | null>(null);
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set());
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [fitSeq, setFitSeq] = useState(0);
  const [viewerError, setViewerError] = useState<string | null>(null);
  /** Запасной простой просмотр: на случай, если просмотрщик Speckle не запустился. */
  const [simpleViewer, setSimpleViewer] = useState(false);
  const [colorByCategory, setColorByCategory] = useState(false);

  const data = detail.data ?? null;
  const storeys = data?.storeys ?? [];
  const parts = useMemo(() => data?.parts ?? [], [data]);
  const warnings = data?.warnings ?? [];
  const storey =
    storeys.find((item) => item.storey_key === storeyChoice) ??
    storeys.find((item) => geometryOf(parts, item.storey_key).length > 0) ??
    null;
  const geometryParts = useMemo(
    () => (storey !== null ? geometryOf(parts, storey.storey_key) : []),
    [parts, storey],
  );
  const elementsPart =
    parts.find((part) => part.kind === 'elements' && part.storey_key === storey?.storey_key) ??
    null;
  const geometry = useStoreyGeometry(projectId, data?.id ?? null, geometryParts);
  const elements = useStoreyElements(projectId, data?.id ?? null, elementsPart);
  // Просмотрщик Speckle собирает объекты вместе со свойствами: ждём элементы, чтобы не грузить дважды.
  const propertiesPending = elementsPart !== null && elements.isPending;
  const viewerParts: IModelPartInput[] = useMemo(
    () => (propertiesPending && !simpleViewer ? [] : [...geometry.parts]),
    [geometry.parts, propertiesPending, simpleViewer],
  );
  const disciplines = useMemo(
    () => [...new Set(geometryParts.map((part) => part.discipline ?? ''))].sort(),
    [geometryParts],
  );
  const element: IModelElement | null =
    selectedId === null ? null : (elements.data?.get(selectedId) ?? null);

  if (versions.isPending) return <SkeletonRows rows={6} />;
  if (versions.isError) {
    return (
      <ErrorState
        title="Не удалось получить версии модели"
        code={extractCode(versions.error)}
        onRetry={() => void versions.refetch()}
      />
    );
  }
  if (versionId === null) {
    return (
      <EmptyState
        title="Модели пока нет"
        description="IFC проекта разбирает портал: загрузите их обычными документами и постройте модель. Версия появится здесь кандидатом и ждёт утверждения."
        action={<ModelImportPanel projectId={projectId} />}
      />
    );
  }

  const status = data ? (MODEL_STATUS[data.status] ?? MODEL_STATUS.uploading) : null;

  return (
    <div
      className="grid min-h-0 flex-1 grid-cols-[260px_minmax(0,1fr)_320px] max-lg:grid-cols-1"
      data-testid="model-screen"
    >
      <aside className={`${SIDE} border-r border-border`} aria-label="Версии и этажи">
        <ModelImportPanel projectId={projectId} />
        <label className="flex flex-col gap-[var(--s-1)] text-xs text-muted">
          Версия модели
          <select
            className="rounded-[var(--radius-sm)] border border-border bg-surface p-[var(--s-2)] text-sm text-fg"
            value={versionId}
            onChange={(event) => {
              setChosen(event.target.value);
              setStoreyChoice(null);
              setSelectedId(null);
            }}
          >
            {items.map((item) => (
              <option key={item.id} value={item.id}>
                № {item.number} · {MODEL_STATUS[item.status]?.label ?? item.status}
              </option>
            ))}
          </select>
        </label>
        {data && status && (
          <div className="flex flex-col gap-[var(--s-2)] text-xs text-muted">
            <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
            <span>
              Этажей: {String(data.counts?.storeys ?? storeys.length)} · элементов:{' '}
              {String(data.counts?.elements ?? '—')}
            </span>
            {data.generator && <span>Выгрузчик: {data.generator}</span>}
            {data.status === 'candidate' && (
              <Button
                variant="primary"
                disabled={approve.isPending}
                onClick={() => approve.mutate({ versionId: data.id })}
              >
                Утвердить версию
              </Button>
            )}
            {approve.isError && (
              <span role="alert" className="text-[var(--danger)]">
                Не удалось утвердить: {extractCode(approve.error) ?? 'ошибка'}
              </span>
            )}
          </div>
        )}
        {detail.isPending && versionId !== null && <SkeletonRows rows={4} />}
        {detail.isError && (
          <ErrorState title="Версию не удалось открыть" code={extractCode(detail.error)} />
        )}
        {data && (
          <ul className="flex flex-col gap-[var(--s-1)]" aria-label="Этажи">
            {[...storeys].reverse().map((item) => {
              const active = storey?.storey_key === item.storey_key;
              return (
                <li key={item.storey_key}>
                  <button
                    type="button"
                    aria-pressed={active}
                    onClick={() => {
                      setStoreyChoice(item.storey_key);
                      setSelectedId(null);
                    }}
                    className={`flex w-full items-baseline justify-between gap-[var(--s-2)] rounded-[var(--radius-sm)] border px-[var(--s-2)] py-[var(--s-2)] text-left text-sm ${
                      active
                        ? 'border-accent bg-surface-muted'
                        : 'border-transparent hover:bg-surface-muted'
                    }`}
                  >
                    <span className="min-w-0 truncate">{item.name}</span>
                    <span className="shrink-0 text-xs text-muted">
                      {formatElevation(item.elevation_mm)}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </aside>

      <section className="relative flex min-h-0 min-w-0 flex-col" aria-label="3D этажа">
        {storey === null ? (
          <EmptyState title="В версии нет этажей с геометрией" compact />
        ) : (
          <>
            {simpleViewer ? (
              <ModelViewerCanvas
                parts={viewerParts}
                hiddenDisciplines={hidden}
                selectedId={selectedId}
                fitSeq={fitSeq}
                onPick={setSelectedId}
                onError={setViewerError}
              />
            ) : (
              <ModelSpeckleCanvas
                parts={viewerParts}
                elements={elements.data ?? null}
                hiddenDisciplines={hidden}
                selectedId={selectedId}
                colorByCategory={colorByCategory}
                fitSeq={fitSeq}
                onPick={setSelectedId}
                onError={setViewerError}
              />
            )}
            <div className="absolute left-[var(--s-3)] top-[var(--s-3)] flex items-center gap-[var(--s-2)] text-xs text-muted">
              <Button onClick={() => setFitSeq((value) => value + 1)}>Вписать</Button>
              {geometry.loading && <span role="status">Загрузка геометрии…</span>}
              {(geometry.failed || viewerError !== null) && (
                <span role="alert" className="text-[var(--danger)]">
                  {viewerError ?? 'Часть геометрии не загрузилась'}
                </span>
              )}
            </div>
          </>
        )}
      </section>

      <aside className={`${SIDE} border-l border-border`} aria-label="Слои и свойства">
        {disciplines.length > 0 && (
          <fieldset className="flex flex-col gap-[var(--s-2)]">
            <legend className="mb-[var(--s-1)] text-xs text-muted">Дисциплины</legend>
            {disciplines.map((code) => (
              <label key={code} className="flex items-center gap-[var(--s-2)] text-sm">
                <input
                  type="checkbox"
                  checked={!hidden.has(code)}
                  onChange={(event) =>
                    setHidden((previous) => {
                      const next = new Set(previous);
                      if (event.target.checked) next.delete(code);
                      else next.add(code);
                      return next;
                    })
                  }
                />
                {code}
              </label>
            ))}
          </fieldset>
        )}
        <fieldset className="flex flex-col gap-[var(--s-2)]">
          <legend className="mb-[var(--s-1)] text-xs text-muted">Вид</legend>
          {!simpleViewer && (
            <label className="flex items-center gap-[var(--s-2)] text-sm">
              <input
                type="checkbox"
                checked={colorByCategory}
                onChange={(event) => setColorByCategory(event.target.checked)}
              />
              Раскрасить по категориям
            </label>
          )}
          <label className="flex items-center gap-[var(--s-2)] text-sm">
            <input
              type="checkbox"
              checked={simpleViewer}
              onChange={(event) => {
                setSimpleViewer(event.target.checked);
                setViewerError(null);
              }}
            />
            Простой просмотр
          </label>
        </fieldset>
        {element ? (
          <section aria-label="Свойства элемента" className="flex flex-col gap-[var(--s-2)]">
            <h2 className="text-sm font-medium">{elementTitle(element)}</h2>
            <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-[var(--s-3)] gap-y-[var(--s-1)] text-xs">
              {propertyRows(element).map((row) => (
                <div key={row.label} className="contents">
                  <dt className="text-muted">{row.label}</dt>
                  <dd className="[overflow-wrap:anywhere]">{row.value}</dd>
                </div>
              ))}
            </dl>
          </section>
        ) : (
          <p className="text-xs text-muted">Щёлкните по элементу, чтобы увидеть его свойства.</p>
        )}
        {warnings.length > 0 && (
          <details className="text-xs text-muted">
            <summary>Замечания проверки: {warnings.length}</summary>
            <ul className="list-disc pl-[var(--s-5)]">
              {warnings.map((warning) => (
                <li key={`${warning.code}|${warning.where}`}>{warning.message}</li>
              ))}
            </ul>
          </details>
        )}
      </aside>
    </div>
  );
};
