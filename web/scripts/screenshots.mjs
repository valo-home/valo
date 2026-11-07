// Снимки интерфейса для README и страницы организации на GitHub. Запуск против демо с английскими названиями (MOCKS_LANG=en)
//   node scripts/screenshots.mjs http://localhost:3000 ../assets/screenshots [имя ...]
import { chromium } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

const [, , base = 'http://localhost:3000', out = 'screenshots', ...only] = process.argv;
const LANG = process.env.SHOTS_LANG || 'en';
const LOCALE = LANG === 'en' ? 'en-US' : LANG;
const DESK = { width: 1440, height: 900 };
const PHONE = { width: 390, height: 844 };

const tab = (n) => async (p) => p.locator('.tabs > button, .tabs .th > button').nth(n).click();
const sub = (n) => async (p) => p.locator('.subn button').nth(n).click();
const press = (re) => async (p) => p.getByRole('button', { name: re }).first().click();
const scroll = (y) => async (p) => p.evaluate((d) => window.scrollBy(0, d), y);
const node = (n) => async (p) => p.locator('.svelte-flow__node').nth(n).click();
const ask = (q) => async (p) => {
	await p.locator('textarea').fill(q);
	await p.locator('textarea').press('Enter');
	await p.waitForTimeout(6000);
};

export const SHOTS = [
	{ name: 'dashboard', path: '/boards/main', theme: 'dark' },
	{ name: 'dashboard-light', path: '/boards/main', theme: 'light' },
	{ name: 'energy', path: '/boards/energy', theme: 'dark' },
	{ name: 'home', path: '', theme: 'dark' },
	{ name: 'rooms', path: '/rooms', theme: 'dark' },
	{ name: 'devices', path: '/devices', theme: 'dark' },
	{ name: 'device', path: '/devices/0x000b57ff0185ac51', theme: 'dark' },
	{ name: 'flows', path: '/flows', theme: 'dark' },
	{ name: 'scenes', path: '/flows', theme: 'dark', acts: [tab(1)] },
	{ name: 'flow-editor', path: '/flows/sauna', theme: 'dark', acts: [node(2)] },
	{ name: 'cameras', path: '/cameras', theme: 'dark', wait: 9000 },
	{ name: 'camera', path: '/cameras/{cam0}', theme: 'dark', wait: 9000 },
	{ name: 'camera-timeline', path: '/cameras/{cam0}?tab=timeline', theme: 'dark', wait: 4000 },
	{ name: 'camera-media', path: '/cameras/{cam1}?tab=media', theme: 'dark', acts: [scroll(560)], wait: 3000 },
	{ name: 'camera-vision', path: '/cameras/{cam0}/settings?tab=vision', theme: 'dark', wait: 6000 },
	{ name: 'zigbee-network', path: '/zigbee', theme: 'dark', acts: [press(/scan/i), scroll(240)], wait: 6000 },
	{ name: 'zigbee-coordinator', path: '/zigbee', theme: 'dark', acts: [tab(2)] },
	{ name: 'mqtt-map', path: '/mqtt', theme: 'dark', acts: [tab(2)], wait: 3000 },
	{ name: 'extensions', path: '/extensions', theme: 'dark' },
	{ name: 'catalog', path: '/extensions', theme: 'dark', acts: [tab(1)] },
	{ name: 'ext-energy', path: '/x/fi.valo.energy/usage', theme: 'dark' },
	{ name: 'ext-weather', path: '/x/fi.valo.openmeteo/weather', theme: 'dark' },
	{ name: 'assistant', path: '/chat', theme: 'dark', acts: [ask('How is the home?'), ask('Which batteries are low?'), ask('Make a dashboard with the voltage of the PC plug')] },
	{ name: 'system', path: '/system', theme: 'dark', acts: [sub(4)] },
	{ name: 'docs', path: '/docs', theme: 'dark' },
	{ name: 'phone-dashboard', path: '/boards/main', theme: 'dark', view: PHONE },
	{ name: 'phone-camera', path: '/cameras/{cam0}', theme: 'dark', view: PHONE, wait: 9000 },
	{ name: 'phone-flows', path: '/flows', theme: 'dark', view: PHONE },
	{ name: 'phone-device', path: '/devices/0x847127ff8d7bbd8d', theme: 'dark', view: PHONE }
];

const browser = await chromium.launch({ channel: process.env.VALO_E2E_CHANNEL || 'chrome', args: [`--lang=${LOCALE}`], env: { ...process.env, LANGUAGE: LOCALE.replace('-', '_'), LANG: `${LOCALE.replace('-', '_')}.UTF-8` } });
const ctx = await browser.newContext({ baseURL: base, locale: LOCALE, deviceScaleFactor: 2, timezoneId: process.env.SHOTS_TZ || 'Europe/Helsinki' });
const page = await ctx.newPage();
fs.mkdirSync(out, { recursive: true });
if (process.env.SHOTS_SETUP) {
	await page.setViewportSize(DESK);
	await page.emulateMedia({ colorScheme: 'dark' });
	await page.goto(`/${LANG}/setup`);
	await page.waitForLoadState('networkidle').catch(() => {});
	await page.locator('input[name="home"]').fill('Virtanen home');
	await page.screenshot({ path: path.join(out, 'setup-home.png') });
	await page.locator('.mf .btn.pri').click();
	await page.waitForTimeout(2500);
	await page.screenshot({ path: path.join(out, 'setup-links.png') });
	await page.locator('.mf .btn.pri').click();
	await page.locator('input[name="name"]').fill('Mikko Virtanen');
	await page.locator('input[name="username"]').fill('mikko');
	await page.screenshot({ path: path.join(out, 'setup-owner.png') });
	console.log('setup shots done');
	await browser.close();
	process.exit(0);
}
await page.goto(`/${LANG}/login`);
await page.locator('input[autocomplete="username"]').fill(process.env.VALO_E2E_USER || 'mikko');
await page.locator('input[type="password"]').fill(process.env.VALO_E2E_PASSWORD || 'valo-demo');
await page.locator('button[type="submit"]').click();
await page.waitForURL((u) => !u.pathname.endsWith('/login'), { timeout: 15_000 });
const cams = await page.evaluate(() => fetch('/api/v1/cameras').then((r) => r.json()));
const ids = (Array.isArray(cams) ? cams : cams.items || []).map((c) => c.id);
fs.mkdirSync(out, { recursive: true });
for (const s of SHOTS) {
	if (only.length && !only.includes(s.name)) continue;
	await page.setViewportSize(s.view || DESK);
	await page.emulateMedia({ colorScheme: s.theme });
	const url = `/${LANG}${s.path.replace('{cam0}', ids[0]).replace('{cam1}', ids[1] || ids[0])}`;
	await page.goto(url);
	await page.waitForLoadState('networkidle').catch(() => {});
	await page.waitForTimeout(1200);
	for (const a of s.acts || []) {
		await a(page);
		await page.waitForTimeout(900);
	}
	await page.waitForTimeout(s.wait || 0);
	const file = path.join(out, `${s.name}.png`);
	await page.screenshot({ path: file });
	console.log(file);
}
await browser.close();
