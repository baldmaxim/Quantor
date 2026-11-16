'use client';

import { useState, type FC } from 'react';

import { Button, ErrorState, SegmentedControl, SkeletonRows, type ISegmentedOption } from '@/components/ui';
import { formatTime } from '@/lib/cad/format';
import {
  MAX_STYLE_SAMPLES,
  STYLE_CLASSES,
  parseStylePreview,
  profileSourceText,
  sampleOrdinal,
  styleClassInfo,
} from '@/lib/cad/style-profile';

import { CadStylePreviewResultView } from './CadStylePreviewResult';
import type { IWorkspaceCadStyle } from './types';

const CLASS_OPTIONS: readonly ISegmentedOption<(typeof STYLE_CLASSES)[number]['id']>[] =
  STYLE_CLASSES.map((item) => ({ value: item.id, label: item.label }));

const ENGINE_NOTE = 'движок пока не учитывает';

/**
 * Раздел «Профиль оформления» (ADR-0049): текущая версия профиля тома, снятие нового профиля
 * по щелчкам-образцам на листе, предпросмотр и принятие. Профиль - оформление проектировщика,
 * а не количество: ничего не считает, а меняет то, как движок читает слои и заливки.
 */
export const CadStylePanel: FC<IWorkspaceCadStyle> = ({
  status,
  current,
  loadError,
  refreshError,
  onReload,
  sampling,
  startDisabledReason,
  onStartSampling,
  onStopSampling,
  activeClass,
  onClassChange,
  negative,
  onNegativeChange,
  samples,
  onRemoveSample,
  onClearSamples,
  preview,
  onPreview,
  accepting,
  onAccept,
  acceptError,
  savedVersion,
}) => {
  const [title, setTitle] = useState('');

  if (status === 'loading') {
    return (
      <div role="status" aria-label="Загрузка профиля оформления">
        <SkeletonRows rows={3} />
      </div>
    );
  }
  if (status === 'error') {
    return (
      <ErrorState
        title="Профиль оформления не загружен"
        description={loadError ?? undefined}
        onRetry={onReload}
      />
    );
  }

  const info = styleClassInfo(activeClass);
  const result = preview?.result ?? null;
  // Разбор один раз: неразобранный предпросмотр принять нельзя.
  const parsed = result === null ? null : parseStylePreview(result.preview);
  const canAccept =
    result?.result_status === 'profile' && parsed !== null && !accepting && acceptError === null;

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-5)]" data-testid="cad-style">
      {refreshError !== null && (
        <div role="alert" className="flex flex-wrap items-center gap-[var(--s-3)] text-xs text-danger">
          <span className="[overflow-wrap:anywhere]">
            Профиль не обновился: {refreshError}
          </span>
          <Button compact onClick={onReload} className="max-md:h-[44px]">
            Повторить
          </Button>
        </div>
      )}
      <section className="flex min-w-0 flex-col gap-[var(--s-2)] text-xs" aria-label="Текущий профиль">
        {current === null ? (
          <p className="text-muted">Профиль не задан — движок выбирает оформление сам.</p>
        ) : (
          <>
            <p className="text-sm">
              Версия {current.version}
              {current.title ? ` · ${current.title}` : ''}
            </p>
            <p className="text-muted">
              {formatTime(current.created_at)} · {profileSourceText(current.source)}
            </p>
          </>
        )}
        {savedVersion !== null && (
          <p role="status" className="text-text">
            Версия {savedVersion} сохранена. Преобразуйте листы тома заново, чтобы применить
            профиль.
          </p>
        )}
      </section>

      {!sampling ? (
        <div className="flex min-w-0 flex-col gap-[var(--s-2)]">
          <Button
            variant="primary"
            disabled={startDisabledReason !== null}
            onClick={onStartSampling}
            className="min-h-[44px] self-start max-md:h-[44px] max-md:w-full"
          >
            {samples.length > 0 ? 'Продолжить по образцам' : 'Снять по образцам'}
          </Button>
          {samples.length > 0 && (
            <p className="text-xs text-muted">Образцов сохранено: {samples.length}.</p>
          )}
          {startDisabledReason !== null && (
            <p className="text-xs text-muted">{startDisabledReason}</p>
          )}
        </div>
      ) : (
        <>
          <p className="text-xs text-muted">
            Щёлкайте по листу: внутри заливок и по штриховке нужного класса. Лист двигается
            перетаскиванием.
          </p>
          <SegmentedControl
            label="Класс образца"
            value={activeClass}
            options={CLASS_OPTIONS}
            onChange={onClassChange}
            layout="wrap"
          />
          {!info.engineSupported && <p className="text-xs text-muted">{info.label}: {ENGINE_NOTE}.</p>}
          <label className="flex min-h-[44px] items-center gap-[var(--s-3)] text-sm">
            <input
              type="checkbox"
              checked={negative}
              onChange={(event) => onNegativeChange(event.target.checked)}
              className="size-5 shrink-0"
            />
            Это НЕ {info.label.toLowerCase()}
          </label>

          <section className="flex min-w-0 flex-col gap-[var(--s-2)]" aria-label="Образцы">
            <div className="flex items-center justify-between gap-[var(--s-3)]">
              <h4 className="text-xs font-medium">
                Образцы: {samples.length} из {MAX_STYLE_SAMPLES}
              </h4>
              <Button
                compact
                disabled={samples.length === 0 || accepting}
                onClick={onClearSamples}
                className="max-md:h-[44px]"
              >
                Очистить всё
              </Button>
            </div>
            {samples.length === 0 ? (
              <p className="text-xs text-muted">Образцов пока нет.</p>
            ) : (
              <ul className="flex min-w-0 flex-col gap-[var(--s-1)]">
                {samples.map((sample, index) => {
                  const own = styleClassInfo(sample.class);
                  const text = `${own.label}${sample.negative ? ' (не)' : ''} №${sampleOrdinal(samples, index)}`;
                  return (
                    <li
                      key={`${index}:${sample.class}:${sample.x}:${sample.y}`}
                      className="flex items-center justify-between gap-[var(--s-3)] text-xs"
                    >
                      <span className="flex items-center gap-[var(--s-2)]">
                        <span
                          aria-hidden="true"
                          className="size-2 shrink-0 rounded-full"
                          style={{ backgroundColor: own.color }}
                        />
                        {text}
                      </span>
                      <Button
                        compact
                        aria-label={`Удалить образец: ${text}`}
                        disabled={accepting}
                        onClick={() => onRemoveSample(index)}
                        className="max-md:h-[44px]"
                      >
                        Удалить
                      </Button>
                    </li>
                  );
                })}
              </ul>
            )}
            {samples.length >= MAX_STYLE_SAMPLES && (
              <p className="text-xs text-muted">Достигнут предел образцов.</p>
            )}
          </section>

          <div className="flex flex-wrap gap-[var(--s-3)]">
            <Button
              variant="primary"
              loading={preview?.running ?? false}
              disabled={samples.length === 0}
              onClick={onPreview}
              className="min-h-[44px] max-md:h-[44px]"
            >
              Предпросмотр
            </Button>
            <Button onClick={onStopSampling} className="min-h-[44px] max-md:h-[44px]">
              Выйти из режима
            </Button>
          </div>

          {preview?.running === true && (
            <p role="status" aria-live="polite" className="text-xs text-muted">
              Движок читает лист. Результат появится сам.
            </p>
          )}
          {preview?.error != null && (
            <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">
              {preview.error}
            </p>
          )}
          {result !== null && (
            <CadStylePreviewResultView result={result} preview={parsed} samples={samples} />
          )}

          {result?.result_status === 'profile' && parsed !== null && (
            <div className="flex min-w-0 flex-col gap-[var(--s-3)]">
              <label className="flex min-w-0 flex-col gap-[var(--s-2)] text-xs text-muted">
                Название версии
                <input
                  type="text"
                  value={title}
                  maxLength={120}
                  onChange={(event) => setTitle(event.target.value)}
                  className="min-h-[44px] rounded-[var(--radius-sm)] border border-border-strong bg-surface px-[var(--s-3)] text-sm text-text"
                />
              </label>
              <Button
                variant="primary"
                loading={accepting}
                disabled={!canAccept}
                onClick={() => onAccept(title)}
                className="min-h-[44px] self-start max-md:h-[44px] max-md:w-full"
              >
                Принять
              </Button>
            </div>
          )}
          {acceptError !== null && (
            <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">
              {acceptError}
            </p>
          )}
        </>
      )}
    </div>
  );
};
