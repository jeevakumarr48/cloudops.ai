import { defineConfig, devices } from '@playwright/test'

// End-to-end tests run the real API (SQLite, no AWS credentials, no AI
// provider) and the Vite dev server, then drive the app in Chromium.
const python = process.env.PYTHON || 'python'
const db = 'sqlite:///./e2e.sqlite3'

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: 'http://127.0.0.1:5173',
    trace: 'retain-on-failure',
    launchOptions: process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {},
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'phone', use: { ...devices['Pixel 7'] } },
  ],
  webServer: [
    {
      command: `cd ../backend && rm -f e2e.sqlite3 && DATABASE_URL=${db} ${python} -m alembic upgrade head && DATABASE_URL=${db} ${python} -m uvicorn main:app --port 8000`,
      url: 'http://127.0.0.1:8000/health',
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      env: {
        CLOUDOPS_COOKIE_SECURE: 'false',
        CLOUDOPS_OPERATOR_EMAILS: 'e2e-operator@example.com',
        CLOUDOPS_AI_PROVIDER: 'none',
        AWS_ACCESS_KEY_ID: 'e2e-not-a-real-key',
        AWS_SECRET_ACCESS_KEY: 'e2e-not-a-real-secret',
        AWS_DEFAULT_REGION: 'us-east-1',
        AWS_EC2_METADATA_DISABLED: 'true',
        // Nothing listens here, so no request can reach real AWS.
        AWS_ENDPOINT_URL: 'http://127.0.0.1:9',
      },
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 5173 --strictPort',
      url: 'http://127.0.0.1:5173',
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
})
