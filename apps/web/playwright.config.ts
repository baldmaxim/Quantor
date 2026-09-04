import { defineConfig, devices } from '@playwright/test';

const PORT = Number(process.env.WEB_PORT ?? 3000);
const baseURL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${PORT}`;

// Рабочая область портала рассчитана на десктоп, поэтому e2e гоняем на типовых разрешениях 1440p/1080p.
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL,
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'desktop-1440',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
    {
      name: 'desktop-1920',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1920, height: 1080 } },
    },
  ],
  // Проверяем собранное приложение, а не dev-сервер: во-первых, это то, что увидит
  // пользователь; во-вторых, HMR-сокет dev-сервера, привязанного к 0.0.0.0, не
  // устанавливается из headless-браузера, и клиент Next не доходит до гидратации.
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        command: `pnpm run build && pnpm exec next start --hostname 127.0.0.1 --port ${PORT}`,
        url: baseURL,
        reuseExistingServer: !process.env.CI,
        timeout: 240_000,
      },
});
