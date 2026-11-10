/**
 * Версия работающей сборки. Страница сверяет её со своей встроенной и так узнаёт
 * о выкладке: байты sw.js между сборками не меняются, и браузер сам нового worker не увидит.
 */

export const dynamic = 'force-dynamic';

export const GET = () => {
  const version = process.env.NEXT_PUBLIC_BUILD_VERSION?.trim() || null;

  return Response.json({ version }, { headers: { 'Cache-Control': 'no-store' } });
};
