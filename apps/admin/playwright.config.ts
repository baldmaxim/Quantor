import { defineConfig, devices } from '@playwright/test';

const PORT = Number(process.env.ADMIN_PORT ?? 3001);
const MOCK_API_PORT = Number(process.env.MOCK_API_PORT ?? 8099);
const baseURL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${PORT}`;
const apiURL = `http://127.0.0.1:${MOCK_API_PORT}`;

// Контур управления десктопный: таблицы прав, настроек и журнала не сжимаются до
// телефона без потери смысла. Телефонный прогон отдельный и проверяет не удобство,
// а отсутствие горизонтального скролла и то, что невозможные действия не предлагаются.
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  // Стенд API поднимается до сервера приложения: серверная проверка прав ходит в него
  // из серверного компонента, мимо браузера, и подменить её из теста нельзя.
  globalSetup: './e2e/mock-api.ts',
  use: {
    baseURL,
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'desktop-1440',
      testIgnore: /mobile\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
    {
      name: 'mobile-390',
      testMatch: /mobile\.spec\.ts/,
      use: { ...devices['iPhone 12'] },
    },
  ],
  // Проверяется собранное приложение, а не dev-сервер: пользователь увидит именно его.
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        command: `pnpm run build && pnpm exec next start --hostname 127.0.0.1 --port ${PORT}`,
        url: baseURL,
        reuseExistingServer: !process.env.CI,
        timeout: 240_000,
        env: {
          API_INTERNAL_BASE_URL: apiURL,
          NEXT_PUBLIC_API_BASE_URL: apiURL,
          NEXT_PUBLIC_BUILD_VERSION: 'e2e',
        },
      },
});
