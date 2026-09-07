import { redirect } from 'next/navigation';
import type { ReactNode } from 'react';

import { ConsoleShell } from '@/components/shell/ConsoleShell';
import { canOpenConsole, fetchSessionState } from '@/lib/server-session';

/**
 * Граница контура управления.
 *
 * Проверка выполняется здесь, на сервере, и возврат происходит **до** построения
 * оболочки: её разметки нет в ответе, и ни один привилегированный запрос не уходит.
 * Клиентская проверка этого не даёт — к моменту её выполнения и то и другое уже
 * случилось (ADR-0013).
 *
 * Три исхода различаются намеренно. Нет сеанса — страница входа. Сеанс есть, права нет —
 * отказ. API не ответил — сообщение о недоступности: отправлять администратора чинить
 * вход, пока лежит сервер, значит мешать ему.
 */

// Ответ зависит от cookie запроса: страницу нельзя ни собрать заранее, ни закэшировать.
export const dynamic = 'force-dynamic';

const ConsoleLayout = async ({ children }: { children: ReactNode }) => {
  const state = await fetchSessionState();

  if (state.kind === 'api-unreachable') redirect('/unavailable');
  if (state.kind === 'anonymous') redirect('/signed-out');
  if (!canOpenConsole(state.session)) redirect('/forbidden');

  return <ConsoleShell session={state.session}>{children}</ConsoleShell>;
};

export default ConsoleLayout;
