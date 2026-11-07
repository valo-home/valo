import { defineConfig } from '@playwright/test';

export default defineConfig({
	testDir: './e2e',
	globalSetup: './e2e/setup.js',
	timeout: 45_000,
	retries: 0,
	workers: 1,
	reporter: [['list']],
	use: {
		baseURL: process.env.VALO_E2E_URL || 'http://localhost:3000',
		extraHTTPHeaders: { origin: process.env.VALO_E2E_URL || 'http://localhost:3000' },
		channel: process.env.VALO_E2E_CHANNEL || 'chrome',
		headless: true,
		locale: 'en-US',
		trace: 'retain-on-failure',
		storageState: 'e2e/.auth.json'
	}
});
