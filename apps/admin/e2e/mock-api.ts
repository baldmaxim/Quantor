import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http';

/**
 * Стенд API для проверок контура управления.
 *
 * Нужен по конкретной причине: граница доступа проверяется **на сервере** админки, и
 * запрос к API уходит из серверного компонента. `page.route` его не перехватит — он
 * идёт мимо браузера. Поэтому поднимается настоящий HTTP-стенд, и приложение ходит в него.
 *
 * Заодно это делает прогон независимым от PostgreSQL и MinIO: проверяется поведение
 * оболочки, а не сохранность данных.
 *
 * Сценарий выбирается значением cookie сеанса — тест ставит её через контекст браузера.
 */

const PLATFORM_ADMIN = {
  authenticated: true,
  auth_mode: 'oidc',
  user: {
    id: '00000000-0000-4000-8000-000000000002',
    email: 'admin@example.com',
    display_name: 'Администратор платформы',
    is_platform_admin: true,
  },
  workspace_id: '00000000-0000-4000-8000-000000000001',
  role: 'platform_admin',
  permissions: [
    'system.admin',
    'settings.read',
    'settings.manage',
    'feature_flags.read',
    'feature_flags.manage',
    'integration.read',
    'integration.manage',
    'audit.read',
  ],
  workspaces: [],
  csrf_token: 'e2e-csrf',
};

const ENGINEER = {
  authenticated: true,
  auth_mode: 'oidc',
  user: {
    id: '00000000-0000-4000-8000-000000000003',
    email: 'engineer@example.com',
    display_name: 'Инженер',
    is_platform_admin: false,
  },
  workspace_id: '00000000-0000-4000-8000-000000000001',
  role: 'engineer',
  permissions: ['project.read', 'document.read'],
  workspaces: [],
  csrf_token: 'e2e-csrf',
};

const ANONYMOUS = { authenticated: false, auth_mode: 'oidc' };

const META = {
  api_version: 'v1',
  schema_version: 1,
  environment: 'test',
  stage: 'stage-2b',
  auth_mode: 'oidc',
  features: { projects: true, documents: true, viewer: true, 'takeoff.ai': false },
};

const SETTINGS = [
  {
    key: 'documents.content_url_ttl_seconds',
    title: 'Время жизни ссылки на файл',
    description: 'Ссылка действует указанное число секунд.',
    category: 'Документы',
    value_type: 'integer',
    value: 3600,
    default_value: 3600,
    source: 'default',
    allowed_scopes: ['system', 'workspace'],
    editable: true,
    restart_required: false,
    is_secret: false,
    minimum: 60,
    maximum: 86400,
    choices: [],
    updated_by: null,
    updated_at: null,
  },
];

const FLAGS = [
  {
    key: 'viewer',
    title: 'Просмотрщик',
    description: 'Просмотр чертежей.',
    stage: 'Этап 1',
    effective: true,
    default: true,
    source: 'default',
    reason: 'умолчание кода',
    admin_editable: true,
    workspace_scoped: true,
    follows_configuration: false,
  },
  {
    key: 'takeoff.manual',
    title: 'Ручные измерения',
    description: 'Калибровка масштаба, счёт, линии и площади. Готово к пилоту.',
    stage: 'Этап 2A · пилот',
    effective: false,
    default: false,
    source: 'default',
    reason: 'умолчание кода',
    admin_editable: true,
    workspace_scoped: true,
    follows_configuration: false,
  },
  {
    key: 'takeoff.ai',
    title: 'Автоматический подсчёт',
    description: 'Распознавание элементов.',
    stage: 'Этап 2',
    effective: false,
    default: false,
    source: 'default',
    reason: 'умолчание кода',
    admin_editable: false,
    workspace_scoped: true,
    follows_configuration: false,
  },
];

const TENDERHUB = {
  configured: false,
  credential_state: 'missing',
  base_url: 'https://tender.example',
  linked_project_count: 0,
};

const READINESS = {
  status: 'ok',
  schema_revision: '0005_project_local_alias',
  components: [
    { name: 'database', status: 'ok', duration_ms: 1.2, detail: null },
    { name: 'database_schema', status: 'ok', duration_ms: 0.8, detail: null },
    { name: 'object_storage', status: 'ok', duration_ms: 2.1, detail: null },
  ],
};

const AUDIT = { items: [], total: 0, limit: 50, offset: 0 };

const JOB_STATS = {
  queued: 0,
  running: 1,
  failed_recently: 2,
  workers_alive: 1,
  workers_total: 1,
};

const WORKERS = [
  {
    id: 'host:42:abc123',
    host: 'host',
    pid: 42,
    version: 'v1',
    started_at: '2026-09-08T10:00:00Z',
    heartbeat_at: '2026-09-08T10:05:00Z',
    current_job_id: null,
    is_alive: true,
  },
];

const JOBS = {
  items: [
    {
      id: '33333333-3333-4333-8333-333333333333',
      project_id: null,
      job_type: 'legacy_import',
      status: 'failed',
      progress: null,
      stage: null,
      error_code: 'ARCHIVE_UNSAFE_PATH',
      error_message: 'в архиве есть небезопасный файл',
      attempt: 1,
      max_attempts: 1,
      worker_id: 'host:42:abc123',
      lease_expires_at: null,
      heartbeat_at: null,
      available_at: '2026-09-08T10:00:00Z',
      started_at: '2026-09-08T10:00:00Z',
      finished_at: '2026-09-08T10:01:00Z',
      created_at: '2026-09-08T10:00:00Z',
      updated_at: '2026-09-08T10:01:00Z',
      // Битый архив: повтор ничего не изменит, и кнопка должна быть заблокирована.
      is_retryable: false,
    },
  ],
  total: 1,
  limit: 25,
  offset: 0,
};

const DIAGNOSTICS = {
  status: 'degraded',
  generated_at: '2026-09-08T10:05:00Z',
  components: [
    {
      name: 'database',
      title: 'PostgreSQL',
      status: 'healthy',
      source: 'live',
      checked_at: '2026-09-08T10:05:00Z',
      duration_ms: 1.2,
      detail: null,
      remediation: null,
      facts: { revision: '0006_job_worker_lease' },
    },
    {
      name: 'job_worker',
      title: 'Исполнитель заданий',
      status: 'not_configured',
      source: 'reported',
      checked_at: '2026-09-08T10:05:00Z',
      duration_ms: null,
      detail: 'исполнитель ни разу не запускался',
      remediation: 'Запустите `pnpm dev:worker`',
      facts: {},
    },
  ],
};

// Пусто намеренно: страница обязана честно сказать, что поставщики не описаны.
const MODEL_PROVIDERS: unknown[] = [];

const sessionFor = (cookie: string): unknown => {
  if (cookie.includes('quantor_session=admin')) return PLATFORM_ADMIN;
  if (cookie.includes('quantor_session=engineer')) return ENGINEER;
  return ANONYMOUS;
};

/**
 * Заголовки доступа с другого источника.
 *
 * Источник отражается, а не заменяется звёздочкой: с `credentials: include` браузер
 * отвергает `*` — и запросы падают ещё до того, как их увидит приложение. Ровно так же
 * ведёт себя настоящий API, у которого список источников задан явно.
 */
const corsHeaders = (origin: string | undefined): Record<string, string> => ({
  'access-control-allow-origin': origin ?? 'http://127.0.0.1:3001',
  'access-control-allow-credentials': 'true',
  'access-control-allow-headers': 'content-type, x-csrf-token, x-workspace-id',
  'access-control-allow-methods': 'GET, POST, PUT, DELETE, OPTIONS',
  vary: 'origin',
});

const json = (
  request: IncomingMessage,
  response: ServerResponse,
  payload: unknown,
  status = 200,
): void => {
  response.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    ...corsHeaders(request.headers.origin),
  });
  response.end(JSON.stringify(payload));
};

const handle = (request: IncomingMessage, response: ServerResponse): void => {
  const url = request.url ?? '';
  const cookie = request.headers.cookie ?? '';

  // Предварительный запрос: заголовок подтверждения делает обращение непростым,
  // и без ответа на OPTIONS браузер до самого запроса не дойдёт.
  if (request.method === 'OPTIONS') {
    response.writeHead(204, corsHeaders(request.headers.origin));
    response.end();
    return;
  }

  if (url.startsWith('/api/v1/auth/session')) return json(request, response, sessionFor(cookie));
  if (url.startsWith('/api/v1/meta')) return json(request, response, META);
  if (url.startsWith('/health/ready')) return json(request, response, READINESS);

  // Всё привилегированное отвечает отказом тому, у кого нет прав, — как настоящий API.
  const session = sessionFor(cookie) as { permissions?: string[] };
  const isAdmin = session.permissions?.includes('system.admin') ?? false;
  if (url.startsWith('/api/v1/admin/')) {
    if (!isAdmin) {
      return json(
        request,
        response,
        { detail: { code: 'PERMISSION_DENIED', message: 'нет прав' } },
        403,
      );
    }
    if (url.includes('/settings')) return json(request, response, SETTINGS);
    if (url.includes('/feature-flags')) return json(request, response, FLAGS);
    if (url.includes('/integrations/tenderhub')) return json(request, response, TENDERHUB);
    if (url.includes('/audit')) return json(request, response, AUDIT);
    if (url.includes('/jobs/stats')) return json(request, response, JOB_STATS);
    if (url.includes('/jobs/workers')) return json(request, response, WORKERS);
    if (url.includes('/jobs')) return json(request, response, JOBS);
    if (url.includes('/diagnostics')) return json(request, response, DIAGNOSTICS);
    if (url.includes('/model-providers')) return json(request, response, MODEL_PROVIDERS);
  }

  json(request, response, { detail: { code: 'NOT_FOUND', message: 'нет такого маршрута' } }, 404);
};

let server: Server | undefined;

export const startMockApi = async (port: number): Promise<void> => {
  server = createServer(handle);
  await new Promise<void>((resolve) => server?.listen(port, '127.0.0.1', resolve));
};

export const stopMockApi = async (): Promise<void> => {
  await new Promise<void>((resolve) => {
    if (!server) return resolve();
    server.close(() => resolve());
  });
};

export default async function globalSetup(): Promise<() => Promise<void>> {
  const port = Number(process.env.MOCK_API_PORT ?? 8099);
  await startMockApi(port);
  return stopMockApi;
}
