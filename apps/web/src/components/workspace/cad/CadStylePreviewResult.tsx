'use client';

import type { CadStylePreviewResult } from '@quantor/api-client';
import type { FC } from 'react';

import {
  NO_SIGNATURE_HINT,
  STATUS_TEXT,
  areaText,
  sampleOrdinal,
  type StylePreview,
  type StyleSample,
  rejectReasonText,
  scaleSourceText,
  shareText,
  styleClassLabel,
} from '@/lib/cad/style-profile';

const LIST = 'flex min-w-0 flex-col gap-[var(--s-2)] text-xs';

interface IProps {
  result: CadStylePreviewResult;
  /** Разобранный `preview`; `null` - формат ответа не совпал с контрактом. */
  preview: StylePreview | null;
  /** Образцы, по которым строился предпросмотр: движок нумерует щелчки сквозным индексом. */
  samples: readonly StyleSample[];
}

const grayClass = (label: string, grays: readonly number[], body: string): string =>
  grays.length === 0 ? `${label}: серый класса не задан` : `${label}: ${body}`;

/** Подпись щелчка: класс, «(не)» у отрицательного и номер внутри класса, как в списке образцов. */
const rejectedLabel = (
  record: { index?: number | undefined; class: string },
  samples: readonly StyleSample[],
): string => {
  const own = typeof record.index === 'number' ? samples[record.index] : undefined;
  if (own === undefined || typeof record.index !== 'number') return styleClassLabel(record.class);
  return `${styleClassLabel(own.class)}${own.negative ? ' (не)' : ''} №${sampleOrdinal(samples, record.index)}`;
};

const fieldSourceText = (source: string): string =>
  source === 'samples' ? 'по образцам' : source.startsWith('base:') ? 'из основы' : source;

/** Итог предпросмотра: что нашёл профиль на листе, источники полей, отклонённые щелчки. */
export const CadStylePreviewResultView: FC<IProps> = ({ result, preview, samples }) => {
  const status = result.result_status;
  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-4)]" data-testid="style-preview-result">
      <p className="text-sm font-medium" role="status">
        {STATUS_TEXT[status]}
      </p>
      {status === 'no_signature' && <p className="text-xs text-muted">{NO_SIGNATURE_HINT}</p>}
      {status === 'profile_out_of_limits' && (
        <ul className={LIST} aria-label="Причины">
          {(result.reasons ?? []).map((reason, index) => (
            <li key={`${reason}:${index}`} className="text-danger [overflow-wrap:anywhere]">
              {reason}
            </li>
          ))}
        </ul>
      )}
      {preview === null ? (
        <p role="alert" className="text-xs text-danger">
          Предпросмотр не разобран: формат ответа движка не совпал с ожидаемым.
        </p>
      ) : (
        <>
          {preview.classes !== null && (
            <section className={LIST} aria-label="Найдено на листе">
              <h4 className="text-xs font-medium">Найдено на листе</h4>
              <p>
                Масштаб: <span className="text-text">{scaleSourceText(result.scale_source)}</span>
              </p>
              <p>
                {grayClass(
                  'Монолит',
                  preview.classes.monolith.grays,
                  `${preview.classes.monolith.fills} заливок, ${areaText(preview.classes.monolith.area_m2)}`,
                )}
              </p>
              <p>
                {grayClass(
                  'Шахты',
                  preview.classes.shaft.grays,
                  `${preview.classes.shaft.fills} заливок, ${areaText(preview.classes.shaft.area_m2)}`,
                )}
              </p>
              <p>
                {grayClass(
                  'Кладка',
                  preview.classes.masonry.grays,
                  `${preview.classes.masonry.hatch_segments} отрезков штриховки`,
                )}
              </p>
              <p>
                Двери: {preview.classes.door.candidates_not_doors} кандидатов по перу не больше{' '}
                {preview.classes.door.pen_max_width} pt
              </p>
              <p>
                Неразобранные заливки: {shareText(preview.unclassified_fill_share)}
              </p>
            </section>
          )}
          {preview.field_sources !== null && (
            <section className={LIST} aria-label="Источники полей">
              <h4 className="text-xs font-medium">Поля профиля</h4>
              <ul className="flex flex-col gap-[var(--s-1)]">
                {Object.entries(preview.field_sources).map(([field, source]) => (
                  <li key={field} className="flex gap-[var(--s-3)]">
                    <span className="mono text-muted">{field}</span>
                    <span>{fieldSourceText(source)}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}
          {preview.rejected_samples.length > 0 && (
            <section className={LIST} aria-label="Отклонённые щелчки">
              <h4 className="text-xs font-medium">Отклонённые щелчки</h4>
              <ul className="flex flex-col gap-[var(--s-1)]">
                {preview.rejected_samples.map((item, index) => (
                  <li key={`${item.reason}:${index}`} className="[overflow-wrap:anywhere]">
                    {rejectedLabel(item.sample, samples)}: {rejectReasonText(item.reason)}
                  </li>
                ))}
              </ul>
            </section>
          )}
          {preview.unsupported_samples.length > 0 && (
            <section className={LIST} aria-label="Неподдерживаемые классы">
              <h4 className="text-xs font-medium">Движок пока не учитывает</h4>
              <ul className="flex flex-col gap-[var(--s-1)]">
                {preview.unsupported_samples.map((item, index) => (
                  <li key={`${item.class}:${index}`}>{styleClassLabel(item.class)}</li>
                ))}
              </ul>
            </section>
          )}
          {preview.warnings.length > 0 && (
            <section className={LIST} aria-label="Предупреждения">
              <h4 className="text-xs font-medium">Предупреждения</h4>
              <ul className="flex flex-col gap-[var(--s-1)]">
                {preview.warnings.map((item, index) => (
                  <li key={`${item.code}:${index}`} className="[overflow-wrap:anywhere]">
                    {item.message}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </div>
  );
};
