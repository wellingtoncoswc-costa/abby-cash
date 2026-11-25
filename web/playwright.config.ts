import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  workers: 1,
  use: { baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5173' },
  projects: [{ name: 'mobile', use: { browserName: 'chromium', viewport: { width: 390, height: 844 } } }],
})
