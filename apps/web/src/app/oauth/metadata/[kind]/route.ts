import { env } from '@/lib/env';

/**
 * Метаданные входа ИИ-чатов по OAuth (ADR-0054) по адресам `/.well-known/…` (см. next.config).
 *
 * Чат ищет их в корне сайта, а корень отдаёт сервер страниц; знает их API (издатель, адреса,
 * области), поэтому здесь только пересылка. Документ публичный: CORS открыт для MCP-клиентов,
 * которые читают его из браузера.
 */

export const dynamic = 'force-dynamic';

const KINDS = new Set(['authorization-server', 'protected-resource']);
const TIMEOUT_MS = 5000;

export const GET = async (
  _request: Request,
  { params }: { params: Promise<{ kind: string }> },
): Promise<Response> => {
  const { kind } = await params;
  if (!KINDS.has(kind)) return new Response('Not found', { status: 404 });

  try {
    const upstream = await fetch(`${env.apiInternalBaseUrl}/api/v1/auth/oauth/metadata/${kind}`, {
      cache: 'no-store',
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: {
        'Content-Type': 'application/json',
        'Cache-Control': upstream.headers.get('cache-control') ?? 'no-store',
        'Access-Control-Allow-Origin': '*',
      },
    });
  } catch {
    return Response.json(
      { error: 'temporarily_unavailable' },
      { status: 503, headers: { 'Cache-Control': 'no-store' } },
    );
  }
};
