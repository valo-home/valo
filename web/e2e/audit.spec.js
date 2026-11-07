import { test } from '@playwright/test';
import fs from 'node:fs';
const OUT = process.env.AUDIT_OUT;
test.skip(!OUT, 'audit runs only through npm run audit');
const DEV = ['fmi-weather', 'safety-safety', '0x000b57ff0185ac51', '0x00158d00227d8b91', '0xa4c138c2e9a0d417', '0x000b57ff3b6896f9', 'sauna-ctrl', 'plugguard-plugs', '0x000b57ff2fb44d09', 'tech-meter', '0x847127ff8d7bbd8d'];
const PAGES = [
	['home', '', []], ['chat', '/chat', []], ['boards', '/boards', []], ['board-main', '/boards/main', []], ['board-widgets', '/boards/widgets', []], ['board-edit', '/boards/main', ['edit']],
	['rooms', '/rooms', []], ['devices', '/devices', []], ['cameras', '/cameras', []], ['camera', '/cameras/dvor', []], ['camera-media', '/cameras/prihozhaya?tab=media', []], ['camera-timeline', '/cameras/dvor?tab=timeline', []], ['camera-settings', '/cameras/prihozhaya/settings?tab=camera', []], ['camera-record', '/cameras/prihozhaya/settings?tab=record', []], ['camera-service', '/cameras/prihozhaya/settings?tab=service', []], ['camera-vision', '/cameras/dvor/settings?tab=vision', []], ...DEV.map((d) => [`dev-${d}`, `/devices/${d}`, []]),
	['flows', '/flows', []], ['scenes', '/flows', ['tab:1']], ['flow-editor', '/flows/kitchen', []],
	['extensions', '/extensions', []], ['ext-catalog', '/extensions', ['tab:1']], ['ext-drawer', '/extensions?open=fi.valo.plugguard', []],
	['x-telegram', '/x/fi.valo.telegram/telegram', []], ['x-safety', '/x/fi.valo.safety/safety', []], ['x-plugs', '/x/fi.valo.plugguard/plugs', []], ['x-calendar', '/x/fi.valo.calendar/calendar', []], ['x-energy', '/x/fi.valo.energy/usage', []], ['x-timers', '/x/fi.valo.timers/timers', []], ['x-weather', '/x/fi.valo.openmeteo/weather', []],
	['zigbee', '/zigbee', []], ['zigbee-devices', '/zigbee', ['tab:1']], ['zigbee-net', '/zigbee', ['tab:2']],
	['mqtt', '/mqtt', []], ['mqtt-disc', '/mqtt', ['tab:1']], ['mqtt-map', '/mqtt', ['tab:2']], ['mqtt-clients', '/mqtt', ['tab:3']],
	['log', '/log', []],
	...['home', 'users', 'tokens', 'backups', 'errors', 'ai', 'about'].map((k, i) => [`sys-${k}`, '/system', [`sub:${i}`]]),
	['docs', '/docs', []], ['docs-scenes', '/docs/scenes', []], ['docs-arch', '/docs/architecture', []], ['docs-ext', '/docs/ext/fi.valo.safety', []]
];
const CONF = [
	['d', 1400, 900, 'light', 'ru'],
	['t', 820, 1000, 'dark', 'uk'],
	['m', 390, 844, 'dark', 'uk'],
	['ml', 390, 844, 'light', 'ru']
];
const probe = () => {
	const out = [];
	const W = innerWidth;
	if (document.documentElement.scrollWidth > W + 1) out.push(`page hscroll ${document.documentElement.scrollWidth}>${W}`);
	const main = document.querySelector('#page') || document.body;
	const label = (e) => `${e.tagName.toLowerCase()}${e.id ? '#' + e.id : ''}${[...e.classList].filter((c) => !c.startsWith('svelte-')).map((c) => '.' + c).join('')} "${(e.textContent || '').trim().slice(0, 40)}"`;
	const scrollable = (e) => { const cs = getComputedStyle(e); return /(auto|scroll)/.test(cs.overflowX + cs.overflowY); };
	for (const e of main.querySelectorAll('*')) {
		const r = e.getBoundingClientRect();
		if (!r.width || !r.height) continue;
		const cs = getComputedStyle(e);
		if (cs.position === 'fixed' || cs.visibility === 'hidden' || e.closest('details:not([open]) > :not(summary)')) continue;
		let p = e.parentElement, clip = false;
		while (p && p !== main) { if (scrollable(p) || getComputedStyle(p).overflow === 'hidden') { clip = true; break; } p = p.parentElement; }
		if (!clip && r.right > W + 1 && !e.closest('svg')) out.push(`beyond viewport ${Math.round(r.right)} ${label(e)}`);
		const card = e.parentElement?.closest('.card, .modal, dialog, .pop');
		if (card && !e.closest('svg') && !clip) {
			const c = card.getBoundingClientRect();
			if (r.right > c.right + 2 || r.bottom > c.bottom + 2 || r.left < c.left - 2) out.push(`outside card ${Math.round(r.right - c.right)}/${Math.round(r.bottom - c.bottom)} ${label(e)}`);
		}
		if (e.children.length === 0 && e.textContent.trim() && cs.overflow !== 'visible' && cs.textOverflow !== 'ellipsis' && e.scrollWidth > e.clientWidth + 2 && !scrollable(e)) out.push(`clipped text ${label(e)}`);
	}
	return [...new Set(out)].slice(0, 40);
};
for (const [cn, w, h, cs, lang] of CONF) {
	test(`audit ${cn}`, async ({ page }) => {
		fs.mkdirSync(OUT, { recursive: true });
		test.setTimeout(600000);
		await page.setViewportSize({ width: w, height: h });
		await page.emulateMedia({ colorScheme: cs });
		const report = {};
		for (const [name, path, acts] of PAGES) {
			const errs = [];
			const onE = (e) => errs.push(String(e.message || e).slice(0, 160));
			const onC = (m) => m.type() === 'error' && errs.push(m.text().slice(0, 160));
			page.on('pageerror', onE); page.on('console', onC);
			try {
				await page.goto(`/${lang}${path}`);
				await page.waitForLoadState('networkidle').catch(() => {});
				await page.waitForTimeout(700);
				for (const a of acts) {
					if (a === 'edit') await page.locator('.ph .row .btn').first().click();
					if (a.startsWith('tab:')) await page.locator('.tabs > button, .tabs .th > button').nth(+a.slice(4)).click();
					if (a.startsWith('sub:')) await page.locator('.subn button').nth(+a.slice(4)).click();
					await page.waitForTimeout(700);
				}
				report[name] = { issues: await page.evaluate(probe), errors: errs };
				await page.screenshot({ path: `${OUT}/${cn}-${name}.png`, fullPage: true });
			} catch (e) {
				report[name] = { fail: String(e.message).slice(0, 200), errors: errs };
			}
			page.off('pageerror', onE); page.off('console', onC);
		}
		fs.writeFileSync(`${OUT}/${cn}.json`, JSON.stringify(report, null, 1));
		const bad = Object.entries(report).filter(([, v]) => v.fail || v.issues?.some((i) => !i.includes('span.vis')));
		console.log(`audit ${cn}: ${bad.length} pages with findings${bad.length ? ': ' + bad.map(([k]) => k).join(', ') : ''}`);
	});
}
