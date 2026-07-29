import { defineConfig } from '@playwright/test';

const baseURL = process.env.VFOOT_E2E_BASE_URL || 'http://127.0.0.1:5173';

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  timeout: 45_000,
  reporter: 'line',
  use: {
    baseURL,
    // The PWA specs need a real Chrome: the bundled headless shell has no service
    // worker DevTools domain, so `ServiceWorker.deliverPushMessage` is unavailable.
    channel: 'chrome',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 5173',
    url: baseURL,
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
