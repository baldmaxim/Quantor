import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const check = vi.fn();
const decide = vi.fn();

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  oauthAuthorizeCheck: (...args: unknown[]) => check(...args),
  oauthAuthorizeDecide: (...args: unknown[]) => decide(...args),
}));

import { OAuthConsent } from './OAuthConsent';

const QUERY =
  'response_type=code&client_id=qoc_1&redirect_uri=https%3A%2F%2Fclaude.ai%2Fapi%2Fmcp%2Fauth_callback&state=s&code_challenge=x&code_challenge_method=S256&scope=read+upload';

const assign = vi.fn();

beforeEach(() => {
  check.mockReset();
  decide.mockReset();
  assign.mockReset();
  vi.stubGlobal('location', { ...window.location, assign });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('OAuthConsent', () => {
  it('показывает чат и передаёт решение с выбранными областями', async () => {
    check.mockResolvedValue({
      data: {
        client_name: 'Claude',
        redirect_host: 'claude.ai',
        local_app: false,
        scopes: ['read', 'upload'],
        scope_titles: { read: 'читать проекты', upload: 'загружать IFC' },
        workspace_name: 'СУ-10',
        already_connected: false,
        error_redirect: null,
      },
    });
    decide.mockResolvedValue({
      data: { redirect_to: 'https://claude.ai/api/mcp/auth_callback?code=c' },
    });
    render(<OAuthConsent query={QUERY} />);

    expect(await screen.findByText('«Claude»')).toBeInTheDocument();
    expect(check).toHaveBeenCalledWith(
      expect.objectContaining({ query: expect.objectContaining({ client_id: 'qoc_1' }) }),
    );
    const read = screen.getByRole('checkbox', { name: 'читать проекты' });
    expect(read).toBeChecked();
    expect(read).toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox', { name: 'загружать IFC' }));
    fireEvent.click(screen.getByRole('button', { name: 'Разрешить' }));

    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith('https://claude.ai/api/mcp/auth_callback?code=c'),
    );
    expect(decide).toHaveBeenCalledWith(
      expect.objectContaining({
        body: expect.objectContaining({
          approve: true,
          scopes: ['read'],
          params: expect.objectContaining({ state: 's' }),
        }),
      }),
    );
  });

  it('сразу возвращает чат, если запрос с ошибкой', async () => {
    check.mockResolvedValue({
      data: { error_redirect: 'https://claude.ai/cb?error=invalid_request' },
    });
    render(<OAuthConsent query={QUERY} />);
    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith('https://claude.ai/cb?error=invalid_request'),
    );
    expect(screen.queryByRole('button', { name: 'Разрешить' })).not.toBeInTheDocument();
  });

  it('объясняет человеку, если чат не зарегистрирован', async () => {
    check.mockRejectedValue({
      error: {
        detail: { code: 'VALIDATION_FAILED', message: 'Чат не зарегистрирован на портале' },
      },
    });
    render(<OAuthConsent query={QUERY} />);
    expect(await screen.findByText('Запрос чата не принят')).toBeInTheDocument();
    expect(assign).not.toHaveBeenCalled();
  });
});
