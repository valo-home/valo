// Один вход на весь прогон через обычную форму входа, сессия сохраняется в e2e/.auth.json. Повторные входы в каждом тесте упираются в лимит попыток входа
import { chromium } from '@playwright/test';

export default async function setup(config) {
	const { baseURL, channel } = config.projects[0].use;
	const browser = await chromium.launch({ channel });
	const ctx = await browser.newContext({ baseURL });
	const page = await ctx.newPage();
	await page.goto('/en/login');
	await page.getByLabel('Username').fill(process.env.VALO_E2E_USER || 'mikko');
	await page.getByLabel('Password').fill(process.env.VALO_E2E_PASSWORD || 'valo-demo');
	await page.getByRole('button', { name: 'Sign in' }).click();
	await page.waitForURL((u) => !u.pathname.endsWith('/login'), { timeout: 15_000 }).catch(async () => {
		throw new Error(`e2e login failed: ${await page.locator('.err').textContent().catch(() => 'no message')}`);
	});
	await ctx.storageState({ path: 'e2e/.auth.json' });
	await browser.close();
}
