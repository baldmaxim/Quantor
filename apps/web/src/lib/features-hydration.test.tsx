import type { MetaResponse } from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act } from 'react';
import { hydrateRoot } from 'react-dom/client';
import { renderToString } from 'react-dom/server';
import { afterEach, describe, expect, it } from 'vitest';

import { queryKeys, useFeatures } from '@/lib/queries';

/**
 * Флаги и гидратация.
 *
 * Регрессия пилота ручного обмера (ADR-0023): страница гидрировалась, когда `meta` уже лежала
 * в кэше, клиент рисовал вкладку включённой, а серверная разметка — выключенной. React 19
 * расхождение атрибутов при гидратации не исправляет, и `disabled` оставался навсегда.
 */

const Probe = () => {
  const features = useFeatures();
  return (
    <button type="button" disabled={features['takeoff.manual'] !== true}>
      Обмеры
    </button>
  );
};

const META: MetaResponse = {
  api_version: '1.0.0',
  schema_version: 10,
  environment: 'test',
  stage: 'stage-2b',
  features: { 'takeoff.manual': true },
  auth_mode: 'dev',
};

const client = (meta: MetaResponse | null): QueryClient => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Number.POSITIVE_INFINITY } },
  });
  if (meta) queryClient.setQueryData(queryKeys.meta, meta);
  return queryClient;
};

const containers: HTMLElement[] = [];

afterEach(() => {
  for (const container of containers.splice(0)) container.remove();
});

describe('флаги возможностей при гидратации', () => {
  it('meta, пришедшая до гидратации, всё равно включает вкладку', async () => {
    // Сервер meta не запрашивает: разметка приходит с выключенной вкладкой.
    const html = renderToString(
      <QueryClientProvider client={client(null)}>
        <Probe />
      </QueryClientProvider>,
    );
    expect(html).toContain('disabled');

    const container = document.createElement('div');
    container.innerHTML = html;
    document.body.append(container);
    containers.push(container);

    // На клиенте meta уже в кэше к моменту гидратации — ровно тот порядок, который ломался.
    await act(async () => {
      hydrateRoot(
        container,
        <QueryClientProvider client={client(META)}>
          <Probe />
        </QueryClientProvider>,
      );
    });

    expect(container.querySelector('button')?.disabled).toBe(false);
  });

  it('выключенный пилот оставляет вкладку выключенной и после гидратации', async () => {
    const html = renderToString(
      <QueryClientProvider client={client(null)}>
        <Probe />
      </QueryClientProvider>,
    );

    const container = document.createElement('div');
    container.innerHTML = html;
    document.body.append(container);
    containers.push(container);

    await act(async () => {
      hydrateRoot(
        container,
        <QueryClientProvider client={client({ ...META, features: { 'takeoff.manual': false } })}>
          <Probe />
        </QueryClientProvider>,
      );
    });

    expect(container.querySelector('button')?.disabled).toBe(true);
  });
});
