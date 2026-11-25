'use client';

import type { ModelSheetOverlayRead, ModelStoreyRead } from '@quantor/api-client';
import { useEffect, useMemo, useRef, useState, type FC } from 'react';

import { useDocumentBackend } from '@/components/viewer/useDocumentBackend';
import { extractCode } from '@/lib/errors';
import {
  fitLabel,
  matrixOf,
  pageCornersMm,
  rasterScale,
  useStoreySheets,
  type ISheetPlaneInput,
} from '@/lib/model/model-sheet-overlay';
import { useContentUrl } from '@/lib/queries';

interface IModelSheetPanelProps {
  readonly projectId: string;
  readonly versionId: string | null;
  /** Этаж, на который кладётся лист; `null` - этаж не выбран. */
  readonly storey: ModelStoreyRead | null;
  /** Номер этажа для разноса этажей (как у частей этажа в просмотрщике). */
  readonly level: number;
  /** Лист для просмотрщика или `null` - убрать. */
  readonly onPlane: (plane: ISheetPlaneInput | null) => void;
}

const keyOf = (item: ModelSheetOverlayRead): string =>
  `${item.revision_id}:${item.page_index}:${item.view}`;

const DEFAULT_OPACITY = 0.7;

/**
 * «Чертёж этажа»: лист плана, привязанный порталом по подписям осей к сетке модели, кладётся на
 * отметку этажа полупрозрачным. Лист рисует pdf.js по временной ссылке на документ; растр
 * ограничен 4096 px по большей стороне. Не привязанные листы показываются с причиной.
 */
export const ModelSheetPanel: FC<IModelSheetPanelProps> = ({
  projectId,
  versionId,
  storey,
  level,
  onPlane,
}) => {
  const [enabled, setEnabled] = useState(false);
  const [chosen, setChosen] = useState<string | null>(null);
  const [opacity, setOpacity] = useState(DEFAULT_OPACITY);
  const [renderError, setRenderError] = useState<string | null>(null);
  const sheets = useStoreySheets(projectId, versionId, storey?.storey_key ?? null, enabled);
  const items = useMemo(() => sheets.data?.items ?? [], [sheets.data]);
  const registered = items.filter((item) => item.status === 'registered');
  const current = registered.find((item) => keyOf(item) === chosen) ?? registered[0] ?? null;
  const content = useContentUrl(enabled && current !== null ? current.revision_id : null);
  const { backend, errorCode } = useDocumentBackend(
    enabled && current !== null ? (content.data?.url ?? null) : null,
  );
  const handler = useRef(onPlane);
  useEffect(() => {
    handler.current = onPlane;
  });
  /** Растр текущего листа: перерисовывается при смене листа, а не при смене прозрачности. */
  const raster = useRef<{
    key: string;
    canvas: HTMLCanvasElement;
    corners: [number, number][];
  } | null>(null);

  useEffect(() => {
    if (!enabled || current === null || backend === null || storey === null) {
      raster.current = null;
      handler.current(null);
      return undefined;
    }
    const matrix = matrixOf(current);
    if (matrix === null) return undefined;
    const key = `${keyOf(current)}@${storey.storey_key}`;
    const controller = new AbortController();
    let cancelled = false;
    void (async () => {
      try {
        const page = await backend.geometry(current.page_index);
        const canvas = document.createElement('canvas');
        await backend.render({
          pageIndex: current.page_index,
          scale: rasterScale(page.width, page.height),
          canvas,
          signal: controller.signal,
          pixelRatio: 1,
        });
        if (cancelled) return;
        const corners = pageCornersMm(matrix, page.width, page.height).map(
          ([x, y]) => [x, y] as [number, number],
        );
        raster.current = { key, canvas, corners };
        setRenderError(null);
        handler.current({
          canvas,
          corners,
          elevationMm: storey.elevation_mm,
          level,
          opacity,
          key,
        });
      } catch {
        if (!cancelled) setRenderError('Лист не нарисовался: документ недоступен или повреждён.');
      }
    })();
    return () => {
      cancelled = true;
      controller.abort();
    };
    // Прозрачность меняется отдельным эффектом ниже: растр при этом не перерисовывается.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    enabled,
    current?.revision_id,
    current?.page_index,
    current?.view,
    backend,
    storey?.storey_key,
    level,
  ]);

  useEffect(() => {
    const ready = raster.current;
    if (!enabled || ready === null || storey === null) return;
    handler.current({
      canvas: ready.canvas,
      corners: ready.corners,
      elevationMm: storey.elevation_mm,
      level,
      opacity,
      key: ready.key,
    });
  }, [opacity, enabled, storey, level]);

  useEffect(() => () => handler.current(null), []);

  return (
    <section className="flex flex-col gap-[var(--s-2)] text-xs" aria-label="Чертёж этажа">
      <label className="flex items-center gap-[var(--s-2)]">
        <input
          type="checkbox"
          checked={enabled}
          disabled={storey === null}
          onChange={(event) => setEnabled(event.target.checked)}
        />
        <span>Чертёж этажа на модели</span>
      </label>
      {enabled && storey === null && <p className="text-muted">Выберите этаж в списке.</p>}
      {enabled && sheets.isPending && (
        <p className="text-muted">Ищем листы плана на отметке этажа…</p>
      )}
      {enabled && sheets.isError && (
        <p className="text-[var(--danger)]">
          Листы не получены ({extractCode(sheets.error) ?? 'ошибка'}). Модель показана без чертежа.
        </p>
      )}
      {enabled && sheets.data?.message && <p className="text-muted">{sheets.data.message}</p>}
      {enabled && registered.length > 1 && (
        <label className="flex flex-col gap-[var(--s-1)] text-muted">
          Лист
          <select
            value={current !== null ? keyOf(current) : ''}
            onChange={(event) => setChosen(event.target.value)}
          >
            {registered.map((item) => (
              <option key={keyOf(item)} value={keyOf(item)}>
                {item.label} · стр. {item.page_index + 1}
              </option>
            ))}
          </select>
        </label>
      )}
      {enabled && current !== null && (
        <>
          <p>
            {current.label} · стр. {current.page_index + 1}
            <br />
            <span className="text-muted">{fitLabel(current)}</span>
          </p>
          <label className="flex flex-col gap-[var(--s-1)] text-muted">
            Прозрачность листа
            <input
              type="range"
              min={0.1}
              max={1}
              step={0.05}
              value={opacity}
              onChange={(event) => setOpacity(Number(event.target.value))}
              aria-label="Прозрачность листа"
            />
          </label>
        </>
      )}
      {enabled && (errorCode !== null || content.isError) && (
        <p className="text-[var(--danger)]">
          Документ листа не открылся. Модель показана без чертежа.
        </p>
      )}
      {enabled && renderError !== null && <p className="text-[var(--danger)]">{renderError}</p>}
      {enabled && items.some((item) => item.status !== 'registered') && (
        <details>
          <summary className="cursor-pointer text-muted">
            Не привязаны: {items.filter((item) => item.status !== 'registered').length}
          </summary>
          <ul className="mt-[var(--s-1)] flex flex-col gap-[var(--s-1)]">
            {items
              .filter((item) => item.status !== 'registered')
              .map((item) => (
                <li key={keyOf(item)}>
                  {item.label} · стр. {item.page_index + 1}: {fitLabel(item)}
                </li>
              ))}
          </ul>
        </details>
      )}
    </section>
  );
};
