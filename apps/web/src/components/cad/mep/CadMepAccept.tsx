'use client';

import type { CadDecisionRead } from '@quantor/api-client';
import { useState, type FC } from 'react';

import { Button } from '@/components/ui';
import { acceptBlock, mepErrorText } from '@/lib/cad/mep-gates';
import { routesDxfUrl, useAcceptMepRoutes } from '@/lib/cad/mep-queries';
import type { ICadViewParams } from '@/lib/cad/view-queries';

import { CadMepDecision } from './CadMepDecision';

interface ICadMepAcceptProps {
  /** Route-задание, его попытка с результатом, лист и вид. */
  params: ICadViewParams;
  acceptance: CadDecisionRead | null;
  /** Открытые замечания на route-задании; `null` - ещё не прочитаны. */
  openRemarks: number | null;
}

const DOWNLOAD =
  'ctl press inline-flex h-[var(--h-ctl)] items-center justify-center self-start rounded-[var(--radius-sm)] border border-accent bg-accent px-[var(--s-5)] text-sm font-medium text-accent-contrast hover:bg-accent-hover max-md:h-[44px] max-md:w-full';

/**
 * Принятие трасс этажа целиком и скачивание 3D DXF. Файл отдаётся сервером только после принятия;
 * до него кнопки скачивания нет.
 */
export const CadMepAccept: FC<ICadMepAcceptProps> = ({ params, acceptance, openRemarks }) => {
  const accept = useAcceptMepRoutes(params);
  const [problem, setProblem] = useState<string | null>(null);

  if (acceptance) {
    return (
      <div className="flex min-w-0 flex-col gap-[var(--s-3)]">
        <CadMepDecision title="Трассы приняты (этаж целиком)" decision={acceptance} />
        <a href={routesDxfUrl(params)} download className={DOWNLOAD}>
          Скачать 3D DXF
        </a>
      </div>
    );
  }

  const block = acceptBlock(acceptance, openRemarks);

  return (
    <div className="flex min-w-0 flex-col items-start gap-[var(--s-3)]">
      <Button
        variant="primary"
        loading={accept.isPending}
        disabled={block !== null}
        onClick={() => {
          setProblem(null);
          accept.mutate({}, { onError: (error) => setProblem(mepErrorText(error)) });
        }}
        className="max-md:h-[44px] max-md:w-full"
      >
        Принять трассы (этаж целиком)
      </Button>
      {block ? (
        <p className="text-xs text-muted" role="note">
          {block}
        </p>
      ) : (
        <p className="text-xs text-muted">3D DXF станет доступен после принятия.</p>
      )}
      {problem && (
        <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">
          {problem}
        </p>
      )}
    </div>
  );
};
