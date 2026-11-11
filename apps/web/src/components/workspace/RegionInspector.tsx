'use client';

import type { RegionRead } from '@quantor/api-client';

import { InspectorSection, Field } from '@/components/ui';
import { IconWarning } from '@/components/ui/icons';
import { blockType } from '@/lib/format';

/**
 * Ссылка из пакета, пригодная для перехода.
 *
 * Адрес приходит из недоверенного архива, поэтому схема проверяется явно: `javascript:`
 * в href — это исполнение чужого кода на странице портала. Всё, кроме http(s), остаётся
 * обычным текстом.
 */
const externalHref = (value: string): string | null => {
  try {
    const url = new URL(value);
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : null;
  } catch {
    return null;
  }
};

export const RegionInspector = ({
  region,
  sheetLabel,
}: {
  region: RegionRead;
  sheetLabel: string;
}) => {
  const cropUrl = region.legacy_metadata['crop_url'];
  const cropHref = typeof cropUrl === 'string' ? externalHref(cropUrl) : null;

  return (
    <>
      <InspectorSection title={blockType(region.block_type)}>
        <dl className="grid grid-cols-[92px_1fr] gap-x-[var(--s-4)] gap-y-[var(--s-2)]">
          <Field label="block_id">{region.external_block_id}</Field>
          {region.ordinal !== null && <Field label="Номер">{region.ordinal}</Field>}
          <Field label="Лист">{sheetLabel}</Field>
          <Field label="Форма">{region.shape_type}</Field>
          <Field label="Координаты">
            [{region.coords_norm.map((value) => value.toFixed(3)).join(', ')}]
          </Field>
          <Field label="Простр-во">normalized_page_top_left</Field>
          {region.recognition_status && <Field label="Статус">{region.recognition_status}</Field>}
        </dl>
      </InspectorSection>

      {region.raw_content_md && (
        <InspectorSection title="Распознанный текст">
          {/* Текст пришёл из недоверенного архива и показывается как текст, а не как
              разметка: разбирать его как HTML нельзя. */}
          <pre className="mono max-h-[240px] overflow-auto rounded-[var(--radius-sm)] border border-border bg-surface-sunken p-[var(--s-3)] text-micro leading-relaxed whitespace-pre-wrap text-muted">
            {region.raw_content_md}
          </pre>
        </InspectorSection>
      )}

      {typeof cropUrl === 'string' && (
        <InspectorSection title="Исходные метаданные">
          <p className="flex items-start gap-[var(--s-3)] text-micro text-muted">
            <IconWarning width={13} height={13} className="mt-[2px] flex-none text-warning" />
            {/* Сервер эту ссылку не загружает: пакет должен оставаться самодостаточным.
                Открыть её может человек — и пусть открывает в новой вкладке, не теряя
                рабочую область. */}
            <span className="min-w-0 break-all">
              crop_url — внешняя ссылка, сервер её не загружает:{' '}
              {cropHref ? (
                <a
                  href={cropHref}
                  target="_blank"
                  rel="noopener noreferrer external"
                  title="Открыть вырезку в новой вкладке"
                  className="text-accent underline decoration-dotted underline-offset-2 transition-colors duration-[var(--dur-fast)] hover:decoration-solid"
                >
                  {cropUrl}
                </a>
              ) : (
                cropUrl
              )}
            </span>
          </p>
        </InspectorSection>
      )}
    </>
  );
};
