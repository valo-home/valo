// Проверки в браузере против работающей демо среды (./valo demo up). Запуск npm run e2e
import { expect, test } from '@playwright/test';

const USER = process.env.VALO_E2E_USER || 'mikko';
const PASS = process.env.VALO_E2E_PASSWORD || 'valo-demo';
const LIGHT = '0x000b57ff2fb44d09';

async function login(page) {
	await page.goto('/en');
	await expect(page.locator('#page h1').first()).toBeVisible();
}

function watchErrors(page) {
	const errors = [];
	page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
	page.on('pageerror', (e) => errors.push(e.message));
	return errors;
}

test('login shows environment and rejects a wrong password', async ({ browser }) => {
	const ctx = await browser.newContext({ storageState: { cookies: [], origins: [] } });
	const page = await ctx.newPage();
	await page.goto('/en/login');
	await expect(page.locator('.envb.demo')).toHaveText('demo');
	await page.getByLabel('Username').fill(USER);
	await page.getByLabel('Password').fill('wrong-password');
	await page.getByRole('button', { name: 'Sign in' }).click();
	await expect(page.locator('.err')).toBeVisible();
	await page.getByLabel('Password').fill(PASS);
	await page.getByRole('button', { name: 'Sign in' }).click();
	await page.waitForURL(/\/en$/);
	await expect(page.locator('h1')).toBeVisible();
	await expect(page.locator('#plan > svg')).toBeVisible();
	await ctx.close();
});

test('login and logout work as plain forms without javascript', async ({ browser }) => {
	const ctx = await browser.newContext({ storageState: { cookies: [], origins: [] }, javaScriptEnabled: false });
	const page = await ctx.newPage();
	await page.goto('/en/devices');
	await expect(page).toHaveURL(/\/en\/login\?next=/);
	await page.getByLabel('Username').fill(USER);
	await page.getByLabel('Password').fill(PASS);
	await page.getByRole('button', { name: 'Sign in' }).click();
	await expect(page).toHaveURL(/\/en\/devices$/);
	await page.locator('button.me').click();
	await expect(page).toHaveURL(/\/en\/login$/);
	await page.goto('/en');
	await expect(page).toHaveURL(/\/en\/login/);
	await ctx.close();
});

test('main pages render without console errors', async ({ page }) => {
	const errors = watchErrors(page);
	await login(page);
	for (const p of ['/en/boards', '/en/rooms', '/en/devices', '/en/cameras', '/en/cameras/dvor', '/en/flows', '/en/extensions', '/en/zigbee', '/en/mqtt', '/en/log', '/en/notifications', '/en/system', '/en/docs', '/en/docs/flows']) {
		await page.goto(p);
		await expect(page.locator('#page h1').first()).toBeVisible();
	}
	expect(errors.filter((e) => !e.includes('favicon') && !e.includes('e2e browser error probe'))).toEqual([]);
});

test('bell opens a notification page with details and the list of all notifications', async ({ page }) => {
	const errors = watchErrors(page);
	await login(page);
	await page.goto('/en/devices');
	await page.getByRole('button', { name: 'Notifications', exact: true }).click();
	const item = page.locator('dialog[open] a.dn').first();
	await expect(item).toBeVisible();
	const text = (await item.textContent()).trim();
	await item.click();
	await expect(page).toHaveURL(/\/en\/notifications\/\d+$/);
	await expect(page.locator('#page h1')).toContainText('Notification');
	await expect(page.locator('#page')).toContainText(text);
	await expect(page.getByRole('link', { name: 'Go to source' })).toBeVisible();
	await page.getByRole('link', { name: 'Back' }).click();
	await expect(page).toHaveURL(/\/en\/notifications$/);
	await expect(page.locator('#page a.dn', { hasText: text }).first()).toBeVisible();
	await page.getByRole('button', { name: 'All', exact: true }).click();
	await expect(page.locator('#page a.dn').first()).toBeVisible();
	expect(errors.filter((e) => !e.includes('favicon') && !e.includes('e2e browser error probe'))).toEqual([]);
});

test('device command is confirmed by the device', async ({ page }) => {
	await login(page);
	await page.goto(`/en/devices/${LIGHT}`);
	const toggle = page.getByRole('button', { name: 'Power', exact: true }).first();
	await expect(toggle).toBeVisible();
	const before = (await toggle.getAttribute('aria-pressed')) === 'true';
	await toggle.click();
	await expect(toggle).toHaveAttribute('aria-pressed', String(!before), { timeout: 10_000 });
	await expect(toggle).not.toHaveClass(/pend/, { timeout: 10_000 });
	await toggle.click();
	await expect(toggle).toHaveAttribute('aria-pressed', String(before), { timeout: 10_000 });
});

test('command palette finds a device', async ({ page }) => {
	await login(page);
	await page.waitForLoadState('networkidle');
	await page.keyboard.press('Control+k');
	const input = page.getByPlaceholder('Device, room, scene or page');
	await expect(input).toBeVisible();
	await input.fill('Люстра');
	await input.press('Enter');
	await page.waitForURL(new RegExp(`/en/devices/${LIGHT}`));
});

test('flow dry run shows a trace without sending commands', async ({ page }) => {
	await login(page);
	await page.goto('/en/flows/kitchen');
	await page.getByRole('button', { name: 'Test', exact: true }).click();
	await expect(page.locator('.chip').filter({ hasText: /^(ok|failed|skipped|condition not met|waiting|running)$/ }).first()).toBeVisible({ timeout: 10_000 });
});

test('pairing opens the network with a countdown', async ({ page }) => {
	await login(page);
	await page.getByRole('button', { name: 'Add device' }).first().click();
	await page.getByRole('button', { name: /Open network/ }).click();
	await expect(page.getByText(/network open for \d+ s/)).toBeVisible({ timeout: 10_000 });
	await page.getByRole('button', { name: 'Close network' }).click();
	await page.getByRole('button', { name: 'Close for sure?' }).click();
	await expect(page.getByRole('button', { name: /Open network/ })).toBeVisible();
});

test('phone width has no horizontal page scroll', async ({ browser }) => {
	const ctx = await browser.newContext({ storageState: 'e2e/.auth.json', viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, colorScheme: 'light' });
	const page = await ctx.newPage();
	await login(page);
	await expect(page.locator('#tabbar')).toBeVisible();
	for (const p of ['/en', '/en/devices', '/en/flows', '/en/log', '/en/system']) {
		await page.goto(p);
		await page.waitForLoadState('networkidle');
		const sw = await page.evaluate(() => document.documentElement.scrollWidth);
		expect(sw, p).toBeLessThanOrEqual(391);
	}
	await ctx.close();
});

test('plan editor moves a room with the mouse and cancels without saving', async ({ page }) => {
	await login(page);
	await page.goto('/en/rooms');
	await page.getByRole('button', { name: 'Edit plan' }).first().click();
	const room = page.locator('svg.pe rect.pe-room').first();
	await expect(room).toBeVisible();
	const x0 = await room.getAttribute('x');
	const b = await room.boundingBox();
	await page.mouse.move(b.x + 20, b.y + 20);
	await page.mouse.down();
	await page.mouse.move(b.x + 120, b.y + 60, { steps: 5 });
	await page.mouse.up();
	expect(await room.getAttribute('x')).not.toBe(x0);
	await expect(page.getByRole('button', { name: 'Save' })).toBeEnabled();
	await page.getByRole('button', { name: 'Cancel' }).click();
	await expect(page.locator('svg.pe')).toHaveCount(0);
});

test('errors tab collects browser errors', async ({ page }) => {
	await login(page);
	await page.goto('/en/system?tab=errors');
	await page.waitForLoadState('networkidle');
	await page.evaluate(() => setTimeout(() => { throw new Error('e2e browser error probe'); }, 0));
	await page.waitForTimeout(800);
	await page.getByRole('button', { name: 'Refresh' }).click();
	await expect(page.getByText('Uncaught Error: e2e browser error probe').first()).toBeVisible({ timeout: 10_000 });
});

test('flow editor undo, redo and duplicate without attribution', async ({ page }) => {
	await login(page);
	await page.goto('/en/flows/kitchen');
	const nodes = page.locator('.svelte-flow__node');
	await expect(nodes.first()).toBeVisible();
	await expect(page.locator('.svelte-flow__attribution')).toHaveCount(0);
	const n0 = await nodes.count();
	await nodes.first().click();
	await page.locator('.svelte-flow__pane').focus().catch(() => {});
	await page.getByRole('button', { name: 'Duplicate' }).click();
	await expect(nodes).toHaveCount(n0 + 1);
	await page.keyboard.press('Control+z');
	await expect(nodes).toHaveCount(n0);
	await page.keyboard.press('Control+Shift+z');
	await expect(nodes).toHaveCount(n0 + 1);
	await page.getByRole('button', { name: 'Undo' }).click();
	await expect(nodes).toHaveCount(n0);
	await expect(page.getByRole('button', { name: 'Undo' })).toBeDisabled();
});

test('backup can be downloaded and uploaded back', async ({ page }) => {
	await login(page);
	const list = await page.evaluate(() => fetch('/api/v1/system/backups').then((r) => r.json()));
	const ok = list.find((b) => b.status === 'ok');
	test.skip(!ok, 'no finished backup in demo');
	const bytes = await page.evaluate(async (id) => Array.from(new Uint8Array(await (await fetch(`/api/v1/system/backups/${id}/download`)).arrayBuffer())), ok.id);
	await page.goto('/en/system?tab=backups');
	await page.locator('input[type=file]').setInputFiles({ name: 'e2e-backup.tar.gz', mimeType: 'application/gzip', buffer: Buffer.from(bytes) });
	await expect(page.getByText('Backup e2e-backup.tar.gz uploaded').first()).toBeVisible({ timeout: 15_000 });
	await expect(page.getByText('uploaded', { exact: true }).first()).toBeVisible();
	await page.locator('input[type=file]').setInputFiles({ name: 'bad.tar.gz', mimeType: 'application/gzip', buffer: Buffer.from('not a backup') });
	await expect(page.getByText('The file is not a Valo backup').first()).toBeVisible({ timeout: 15_000 });
});

test('rgb light color and two channel switch', async ({ page }) => {
	await login(page);
	await page.goto('/en/devices/0x0017880108a4c3e1');
	const color = page.locator('input[type=color]');
	await expect(color).toBeVisible();
	await color.evaluate((el) => {
		el.value = '#00ff00';
		el.dispatchEvent(new Event('change', { bubbles: true }));
	});
	await expect(page.getByText('#00ff00').first()).toBeVisible({ timeout: 10_000 });
	await page.goto('/en/devices/0xa4c138c2e9a0d417');
	await expect(page.getByRole('button', { name: 'Power 2', exact: true }).first()).toBeVisible();
	const ch2 = page.getByRole('button', { name: 'Power 2', exact: true }).first();
	const before = (await ch2.getAttribute('aria-pressed')) === 'true';
	await ch2.click();
	await expect(ch2).toHaveAttribute('aria-pressed', String(!before), { timeout: 10_000 });
});

test('energy, weather, calendar and timers extensions show pages and devices', async ({ page }) => {
	const errors = watchErrors(page);
	await login(page);
	for (const [url, text] of [
		['/en/x/fi.valo.energy/usage', 'Usage for 30 days, kWh'],
		['/en/x/fi.valo.openmeteo/weather', 'Daily forecast'],
		['/en/x/fi.valo.calendar/calendar', 'Upcoming holidays'],
		['/en/x/fi.valo.timers/timers', 'Alarms']
	]) {
		await page.goto(url);
		await expect(page.getByText(text, { exact: true }).first()).toBeVisible({ timeout: 15_000 });
	}
	const start = page.getByRole('button', { name: /^Start / }).first();
	const name = (await start.textContent()).replace('Start ', '').trim();
	await start.click();
	const stop = page.getByRole('button', { name: `Stop ${name}` });
	await expect(stop).toBeVisible({ timeout: 10_000 });
	await stop.click();
	await expect(page.getByRole('button', { name: `Start ${name}` })).toBeVisible({ timeout: 10_000 });
	await page.goto('/en/devices?tab=services&q=openmeteo');
	await expect(page.locator('a[href$="/devices/openmeteo-weather"]')).toBeVisible();
	expect(errors).toEqual([]);
});

test('users can be added, disabled and removed from the system page', async ({ page, request }) => {
	const users = await (await request.get('/api/v1/users')).json();
	for (const u of users.filter((x) => x.username === 'e2e-guest')) await request.delete(`/api/v1/users/${u.id}`, { headers: { 'content-type': 'application/json' } });
	await login(page);
	await page.goto('/en/system?tab=users');
	await page.getByRole('button', { name: 'Add user' }).click();
	const dlg = page.getByRole('dialog');
	await dlg.getByLabel('Name', { exact: true }).fill('E2E guest');
	await dlg.getByLabel('Username').fill('e2e-guest');
	await dlg.getByLabel('Password').fill('e2e-guest-pass');
	await dlg.getByLabel('Role').selectOption('guest');
	const kitchen = dlg.getByRole('button', { name: 'Кухня' });
	await kitchen.click();
	await expect(kitchen).toHaveAttribute('aria-pressed', 'true');
	await dlg.getByRole('button', { name: 'Save' }).click();
	const name = page.getByRole('button', { name: 'E2E guest' });
	await expect(name).toBeVisible();
	const ok = await request.post('/api/v1/auth/login', { data: { username: 'e2e-guest', password: 'e2e-guest-pass' } });
	expect(ok.status()).toBe(200);
	await name.click();
	await dlg.getByLabel('Active').uncheck();
	await dlg.getByRole('button', { name: 'Save' }).click();
	await expect(page.getByRole('row', { name: /E2E guest/ })).toContainText('disabled');
	const off = await request.post('/api/v1/auth/login', { data: { username: 'e2e-guest', password: 'e2e-guest-pass' } });
	expect(off.status()).toBe(401);
	await name.click();
	await dlg.getByRole('button', { name: 'Delete' }).click();
	await dlg.getByRole('button', { name: 'Confirm deletion' }).click();
	await expect(name).toHaveCount(0);
});

test('read token works only for reading and stops after deletion', async ({ page, playwright }) => {
	await login(page);
	await page.goto('/en/system?tab=tokens');
	const card = page.locator('section.card').first();
	const label = `E2E token ${Date.now()}`;
	await card.getByLabel('Name').fill(label);
	await card.getByRole('button', { name: 'Create' }).click();
	const token = (await card.locator('code').textContent()).trim();
	expect(token.startsWith('valo_')).toBe(true);
	const api = await playwright.request.newContext({ baseURL: page.url().split('/en/')[0], storageState: { cookies: [], origins: [] }, extraHTTPHeaders: { authorization: `Bearer ${token}` } });
	expect((await api.get('/api/v1/devices')).status()).toBe(200);
	expect((await api.get('/api/v1/users')).status()).toBe(403);
	const row = page.getByRole('row', { name: new RegExp(label) });
	await row.getByRole('button', { name: 'Delete' }).click();
	await row.getByRole('button', { name: 'Confirm deletion' }).click();
	await expect(row).toHaveCount(0);
	expect((await api.get('/api/v1/devices')).status()).toBe(401);
	await api.dispose();
});

test('dashboard widgets reorder with the mouse and the keyboard and the order is saved', async ({ page }) => {
	test.slow();
	await login(page);
	await page.goto('/en/boards');
	await page.getByRole('link', { name: /Моя панель/ }).click();
	await expect(page).toHaveURL(/\/en\/boards\/[^/?]+$/);
	await page.waitForLoadState('networkidle');
	await page.getByRole('button', { name: 'Customize' }).click();
	const titles = () => page.locator('.wg [role=listitem] h3').allTextContents();
	const items = page.locator('.wg [role=listitem]');
	const layout = () => items.evaluateAll((els) => els.map((e) => e.getBoundingClientRect().top).join());
	let last = '';
	await expect.poll(async () => last === (last = await layout())).toBe(true);
	const before = await titles();
	const from = await items.nth(1).locator('h3').boundingBox();
	const to = await items.nth(0).boundingBox();
	await page.mouse.move(from.x + 20, from.y + 8);
	await page.mouse.down();
	await page.mouse.move(to.x + 30, to.y + 30, { steps: 20 });
	const saved = page.waitForResponse((r) => r.url().includes('/api/v1/dashboards/') && r.request().method() === 'PATCH');
	await page.mouse.up();
	await saved;
	const swapped = [before[1], before[0], ...before.slice(2)];
	await expect.poll(titles).toEqual(swapped);
	await page.reload();
	await page.waitForLoadState('networkidle');
	await expect.poll(titles).toEqual(swapped);
	await page.getByRole('button', { name: 'Customize' }).click();
	await items.nth(0).focus();
	await page.keyboard.press('Space');
	await page.keyboard.press('ArrowRight');
	const restored = page.waitForResponse((r) => r.url().includes('/api/v1/dashboards/') && r.request().method() === 'PATCH');
	await page.keyboard.press('Space');
	await restored;
	await expect.poll(titles).toEqual(before);
	await page.reload();
	await expect.poll(titles).toEqual(before);
});

test('room panel assigns an existing device and moves it back', async ({ page, request }) => {
	const lamp = '0x00178801f79be3bd';
	await login(page);
	await page.goto('/en/rooms?room=office');
	const panel = page.getByRole('dialog');
	await panel.getByRole('button', { name: 'Choose existing' }).click();
	await panel.getByRole('searchbox').fill('Торшер');
	await panel.locator('label.pick input').check();
	await panel.getByRole('button', { name: /^Save/ }).click();
	await expect(panel.locator('.drow a.dn', { hasText: 'Торшер' })).toBeVisible();
	expect((await (await request.get(`/api/v1/devices/${lamp}`)).json()).roomId).toBe('office');
	await panel.getByRole('button', { name: 'Choose existing' }).click();
	await panel.getByRole('searchbox').fill('Торшер');
	await panel.locator('label.pick input').uncheck();
	await panel.getByRole('button', { name: /^Save/ }).click();
	await expect(panel.locator('.drow a.dn', { hasText: 'Торшер' })).toHaveCount(0);
	const back = await request.patch(`/api/v1/devices/${lamp}`, { data: { roomId: 'living' } });
	expect(back.ok()).toBe(true);
});

test('widget board shows plug readings, batteries, power and adds a value widget', async ({ page }) => {
	const errors = watchErrors(page);
	await login(page);
	await page.goto('/en/boards');
	await page.getByRole('link', { name: /Обзор виджетов/ }).click();
	const plug = page.locator('section.card', { has: page.getByRole('heading', { name: /Кофемашина/ }) });
	await expect(plug.getByText('Voltage')).toBeVisible();
	await expect(plug.getByText('Today')).toBeVisible();
	await expect(page.locator('section.card', { has: page.getByRole('heading', { name: 'Batteries' }) }).locator('.meter').first()).toBeVisible();
	await expect(page.locator('section.card', { has: page.getByRole('heading', { name: 'Power use' }) })).toContainText('Total');
	await expect(page.locator('section.card', { has: page.getByRole('heading', { name: 'Clock and weather' }) }).locator('b.num').first()).toBeVisible();
	const before = await page.locator('.wg [role=listitem]').count();
	await page.getByRole('button', { name: 'Customize' }).click();
	await page.getByRole('button', { name: 'Add widget' }).click();
	const dlg = page.getByRole('dialog');
	await dlg.getByRole('button', { name: 'Value', exact: true }).click();
	await expect(dlg.getByLabel('Capability')).toBeVisible();
	await dlg.getByRole('button', { name: 'Add', exact: true }).click();
	await expect(page.locator('.wg [role=listitem]')).toHaveCount(before + 1);
	await page.locator('.wg [role=listitem]').last().getByRole('button', { name: 'Delete' }).click();
	await page.locator('.wg [role=listitem]').last().getByRole('button', { name: 'Confirm deletion' }).click();
	await expect(page.locator('.wg [role=listitem]')).toHaveCount(before);
	expect(errors).toEqual([]);
});

test('device and service lists are split into pages of 50', async ({ page, request }) => {
	await login(page);
	const all = await (await request.get('/api/v1/devices')).json();
	for (const [tab, n] of [['devices', all.filter((d) => !d.service).length], ['services', all.filter((d) => d.service).length]]) {
		await page.goto(`/en/devices?tab=${tab}`);
		const rows = page.locator('table tbody tr');
		const nav = page.getByRole('navigation', { name: 'Pages' });
		await expect(rows).toHaveCount(Math.min(n, 50));
		if (n <= 50) {
			await expect(nav).toHaveCount(0);
			continue;
		}
		await expect(nav).toContainText('1-50 of');
		await nav.getByRole('button', { name: 'Next page' }).click();
		await expect(rows).toHaveCount(n - 50 > 50 ? 50 : n - 50);
	}
});

test('assistant builds a dashboard, the user undoes it, and a device command waits for confirmation', async ({ page, request }) => {
	const errors = watchErrors(page);
	await login(page);
	await page.goto('/en/chat');
	const box = page.getByLabel('Message the assistant');
	await box.fill('Make a dashboard with plug voltage');
	await box.press('Enter');
	await expect(page).toHaveURL(/\/en\/chat\?c=/);
	const card = page.locator('.acard').first();
	await expect(card).toContainText('done', { timeout: 20_000 });
	await expect(page.locator('.msg.ai .bub').last()).toContainText('Created dashboard', { timeout: 20_000 });
	const boards = async () => (await (await request.get('/api/v1/dashboards')).json()).map((b) => b.name);
	expect(await boards()).toContain('Voltage');
	await card.getByRole('button', { name: 'Undo' }).click();
	await expect(card).toContainText('undone');
	await expect.poll(boards).not.toContain('Voltage');
	await expect(page.getByRole('button', { name: 'Send' })).toBeVisible();
	await box.fill('Turn on the plug');
	await box.press('Enter');
	const pending = page.locator('.acard.pending');
	await expect(pending).toContainText('awaiting confirmation', { timeout: 20_000 });
	await pending.getByRole('button', { name: 'Decline' }).click();
	await expect(page.locator('.acard').last()).toContainText('declined');
	const id = new URL(page.url()).searchParams.get('c');
	const item = page.locator('.citem', { has: page.locator(`a[href$="${id}"]`) });
	await item.getByRole('button', { name: 'Delete' }).click();
	await item.getByRole('button', { name: 'Confirm deletion' }).click();
	await expect(page).toHaveURL(/\/en\/chat$/);
	expect((await request.get(`/api/v1/chats/${id}`)).status()).toBe(404);
	expect(errors).toEqual([]);
});

test('AI settings tab tests the configured model', async ({ page }) => {
	await login(page);
	await page.goto('/en/system?tab=ai');
	await expect(page.getByLabel('Model')).toHaveValue('valo/demo');
	await page.getByRole('button', { name: 'Test', exact: true }).click();
	await expect(page.getByText(/Model valo\/demo replied: OK/)).toBeVisible({ timeout: 15_000 });
});

test('dashboards open from a list and old board links still work', async ({ page, request }) => {
	await login(page);
	const boards = await (await request.get('/api/v1/dashboards')).json();
	await page.goto('/en/boards');
	const cards = page.locator('a.bcard');
	await expect(cards).toHaveCount(boards.length);
	const first = cards.filter({ hasText: boards[0].name });
	await expect(first).toContainText(new RegExp(`${boards[0].widgets.length} widgets?`));
	await first.click();
	await expect(page).toHaveURL(new RegExp(`/en/boards/${boards[0].id}$`));
	await expect(page.getByRole('heading', { level: 1 })).toHaveText(boards[0].name);
	await page.getByRole('link', { name: 'Back' }).click();
	await expect(page).toHaveURL(/\/en\/boards$/);
	await page.goto(`/en/boards?board=${boards[1].id}`);
	await expect(page).toHaveURL(new RegExp(`/en/boards/${boards[1].id}$`));
	await page.goto('/en/boards/no-such-board');
	await expect(page.getByText('Dashboard not found or deleted.')).toBeVisible();
});

test('device icons move inside a room on the plan and the position is saved', async ({ page, request }) => {
	await login(page);
	const rooms = async () => Object.fromEntries((await (await request.get('/api/v1/rooms')).json()).map((r) => [r.id, r.geom]));
	const before = await rooms();
	await page.goto('/en');
	await page.getByRole('button', { name: 'Edit plan' }).click();
	const mark = page.locator('.pe-dev').first();
	const name = (await mark.getAttribute('aria-label')).replace(/^Move /, '');
	const b = await mark.boundingBox();
	await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2);
	await page.mouse.down();
	await page.mouse.move(b.x + 80, b.y - 90, { steps: 8 });
	await page.mouse.up();
	await expect(page.getByRole('button', { name: 'Back to the row' })).toBeVisible();
	await expect(page.locator('.row b', { hasText: name })).toBeVisible();
	await page.getByRole('button', { name: 'Save' }).click();
	await expect(page.locator('#plan')).toBeVisible();
	const after = await rooms();
	const moved = Object.entries(after).filter(([id, g]) => JSON.stringify(g.devs || {}) !== JSON.stringify(before[id]?.devs || {}));
	expect(moved).toHaveLength(1);
	const [rid, g] = moved[0];
	expect(Object.values(g.devs).every(([x, y]) => x >= 0 && x <= 1 && y >= 0 && y <= 1)).toBe(true);
	expect((await request.patch(`/api/v1/rooms/${rid}`, { data: { geom: before[rid] } })).ok()).toBe(true);
});

test('extension pages fold into one menu item', async ({ page }) => {
	await login(page);
	await page.goto('/en/devices');
	await page.evaluate(() => localStorage.removeItem('valo.nav.ext'));
	await page.reload();
	const nav = page.getByRole('navigation', { name: 'Navigation' });
	const fold = nav.getByRole('button', { name: /Pages/ });
	await expect(fold).toHaveAttribute('aria-expanded', 'false');
	await expect(nav.getByRole('link', { name: 'Telegram' })).toHaveCount(0);
	await fold.click();
	await expect(fold).toHaveAttribute('aria-expanded', 'true');
	await nav.getByRole('link', { name: 'Telegram' }).click();
	await page.reload();
	await expect(nav.getByRole('link', { name: 'Telegram' })).toBeVisible();
});

test('a dashboard widget is reconfigured in place', async ({ page, request }) => {
	await login(page);
	const board = (await (await request.get('/api/v1/dashboards')).json()).find((b) => b.widgets.some((w) => w.type === 'room'));
	const idx = board.widgets.findIndex((w) => w.type === 'room');
	await page.goto(`/en/boards/${board.id}`);
	await page.getByRole('button', { name: 'Customize' }).click();
	const item = page.locator('.wg [role=listitem]').nth(idx);
	await item.getByRole('button', { name: 'Widget settings' }).click();
	const dlg = page.getByRole('dialog');
	const select = dlg.getByLabel('Room');
	const other = await select.locator('option').evaluateAll((o, cur) => o.map((x) => x.value).find((v) => v !== cur), board.widgets[idx].room);
	await select.selectOption(other);
	const saved = page.waitForResponse((r) => r.url().includes(`/api/v1/dashboards/${board.id}`) && r.request().method() === 'PATCH');
	await dlg.getByRole('button', { name: 'Save' }).click();
	await saved;
	const now = (await (await request.get('/api/v1/dashboards')).json()).find((b) => b.id === board.id);
	expect(now.widgets).toHaveLength(board.widgets.length);
	expect(now.widgets[idx]).toMatchObject({ type: 'room', room: other, id: board.widgets[idx].id });
	expect((await request.patch(`/api/v1/dashboards/${board.id}`, { data: { widgets: board.widgets } })).ok()).toBe(true);
});

test('mqtt mappings are listed and open for editing, the tab is kept in the address', async ({ page, request }) => {
	await login(page);
	const mapped = (await (await request.get('/api/v1/devices?limit=500')).json()).filter((d) => d.source === 'map');
	expect(mapped.length).toBeGreaterThan(0);
	await page.goto('/en/mqtt?tab=mapping');
	await expect(page.getByRole('heading', { name: /Mapped devices/ })).toBeVisible();
	const row = page.locator('.row', { has: page.getByRole('link', { name: mapped[0].name }) });
	await row.getByRole('button', { name: 'Edit' }).click();
	await expect(page.getByRole('heading', { name: `Editing mapping ${mapped[0].name}` })).toBeVisible();
	await expect(page.getByLabel('ID')).toHaveValue(mapped[0].id);
	await expect(page.getByLabel('ID')).toBeDisabled();
	await page.getByRole('button', { name: 'Cancel' }).click();
	await expect(page.getByRole('heading', { name: 'New mapping' })).toBeVisible();
	await page.getByRole('button', { name: 'Accounts' }).click();
	await expect(page).toHaveURL(/tab=clients/);
	await expect(page.getByText(/\d+ rules?/).first()).toBeVisible();
});

test('counters use plural forms', async ({ page }) => {
	await login(page);
	await page.goto('/ru/devices');
	await expect(page.locator('.ph p')).toHaveText(/^\d+ устройств(о|а)?, \d+ сервис(а|ов)?, без связи \d+$/);
	await page.goto('/en/rooms');
	await expect(page.locator('.ph p')).toContainText(/\d+ rooms?, \d+ floors?/);
});

test('weather widget shows the chosen city and the calendar widget shows date and time', async ({ page, request }) => {
	await login(page);
	const res = await request.post('/api/v1/dashboards', { data: { name: `e2e weather ${Date.now()}`, widgets: [{ type: 'ext', ext: 'fi.valo.openmeteo', key: 'now', id: 'wnow1' }, { type: 'ext', ext: 'fi.valo.calendar', key: 'today', id: 'wcal1' }] } });
	expect(res.ok(), await res.text()).toBe(true);
	const made = await res.json();
	try {
		await page.goto(`/en/boards/${made.id}`);
		const cal = page.locator('.wg [role=listitem]').nth(1);
		await expect(cal.locator('.bclock b')).toHaveText(/^\d{2}:\d{2}$/);
		const wx = page.locator('.wg [role=listitem]').first();
		await expect(wx.locator('.hero .v')).toContainText('°C');
		await expect(wx.locator('.strip li').first()).toContainText('Now');
		expect(await wx.locator('.strip li').count()).toBe(8);
		await expect(cal.locator('.bclock .day')).toContainText(String(new Date().getFullYear()));
		await page.getByRole('button', { name: 'Customize' }).click();
		await page.locator('.wg [role=listitem]').first().getByRole('button', { name: 'Widget settings' }).click();
		const dlg = page.getByRole('dialog');
		await dlg.getByLabel('City or town').fill('Lviv');
		await dlg.getByRole('button', { name: 'Search' }).click();
		await dlg.getByRole('button', { name: /Lviv/ }).click();
		const saved = page.waitForResponse((r) => r.url().includes(`/api/v1/dashboards/${made.id}`) && r.request().method() === 'PATCH');
		await dlg.getByRole('button', { name: 'Save' }).click();
		await saved;
		const b = (await (await request.get('/api/v1/dashboards')).json()).find((x) => x.id === made.id);
		expect(b.widgets[0].place).toMatchObject({ name: 'Lviv', lat: 49.8397, lon: 24.0297 });
		await page.getByRole('button', { name: 'Done' }).click();
		await expect(page.locator('.wg [role=listitem]').first().locator('.wt small')).toHaveText('Lviv');
		await page.getByRole('button', { name: 'Customize' }).click();
		await cal.getByRole('button', { name: 'Widget settings' }).click();
		await dlg.getByLabel('Title').fill('Today');
		const titled = page.waitForResponse((r) => r.url().includes(`/api/v1/dashboards/${made.id}`) && r.request().method() === 'PATCH');
		await dlg.getByRole('button', { name: 'Save' }).click();
		await titled;
		await expect(cal.locator('.wt > span').first()).toHaveText('Today');
		await expect(cal.locator('.bclock .day')).toContainText(String(new Date().getFullYear()));
	} finally {
		await request.delete(`/api/v1/dashboards/${made.id}`);
	}
});

test('widget heights snap to grid steps and can be set by hand', async ({ page, request }) => {
	await login(page);
	const made = await (await request.post('/api/v1/dashboards', { data: { name: `e2e grid ${Date.now()}`, widgets: [{ type: 'leaks', id: 'h1' }, { type: 'battery', id: 'h2' }] } })).json();
	try {
		await page.goto(`/en/boards/${made.id}`);
		const leaks = page.locator('.wg [role=listitem]').first();
		await expect(leaks).toHaveAttribute('style', /grid-row: span [1-4]/);
		const auto = await leaks.evaluate((e) => e.offsetHeight);
		expect([164, 344, 524, 704]).toContain(auto);
		await page.getByRole('button', { name: 'Customize' }).click();
		const saved = page.waitForResponse((r) => r.url().includes(`/api/v1/dashboards/${made.id}`) && r.request().method() === 'PATCH');
		await leaks.getByRole('button', { name: 'Height: auto' }).click();
		await saved;
		await expect(leaks).toHaveAttribute('style', /grid-row: span 1/);
		await expect(leaks.getByRole('button', { name: 'Height: 1×' })).toBeVisible();
		expect(await leaks.evaluate((e) => e.offsetHeight)).toBe(164);
		const b = (await (await request.get('/api/v1/dashboards')).json()).find((x) => x.id === made.id);
		expect(b.widgets[0].h).toBe(1);
	} finally {
		await request.delete(`/api/v1/dashboards/${made.id}`);
	}
});

test('documentation has sections, search, pages and extension docs', async ({ page }) => {
	const errors = watchErrors(page);
	await login(page);
	await page.goto('/en/docs');
	await expect(page.locator('#page h1')).toHaveText('Documentation');
	await expect(page.locator('.dgrid .card').first()).toBeVisible();
	await page.getByRole('searchbox', { name: 'Search the documentation' }).fill('scene');
	const hit = page.locator('a.hit').first();
	await expect(hit).toBeVisible();
	await page.goto('/en/docs/scenes');
	await expect(page.locator('#page h1')).not.toHaveText('Documentation');
	await expect(page.locator('article.doc')).toContainText(/scene/i);
	await expect(page.locator('.ddesk a[aria-current=page]')).toHaveAttribute('href', '/en/docs/scenes');
	await page.goto('/en/docs/ext/fi.valo.openmeteo');
	await expect(page.locator('article.doc')).toContainText('Open-Meteo');
	await page.goto('/en/docs/no-such-page');
	await expect(page.getByText('Documentation page not found.')).toBeVisible();
	expect(errors.filter((e) => !e.includes('404'))).toEqual([]);
});

test('hint icons explain a section and link to its documentation page', async ({ page }) => {
	await login(page);
	await page.goto('/en/flows');
	const scenes = page.locator('.tabs .th').nth(1);
	await scenes.getByRole('button', { name: 'Explanation' }).click();
	const tip = page.getByRole('tooltip');
	await expect(tip).toContainText('A scene is a saved set of states');
	await page.keyboard.press('Escape');
	await expect(tip).toHaveCount(0);
	await scenes.getByRole('button', { name: 'Explanation' }).click();
	await page.getByRole('tooltip').getByRole('link', { name: /More in the documentation/ }).click();
	await expect(page).toHaveURL(/\/en\/docs\/scenes$/);
});

test('devices and extension services are two lists, sources are named after extensions', async ({ page }) => {
	await login(page);
	await page.goto('/en/devices');
	const tabs = page.locator('.tabs');
	await expect(tabs.getByRole('button', { name: /Devices/ })).toHaveAttribute('aria-pressed', 'true');
	const sources = page.getByRole('group', { name: 'Source' });
	await expect(sources.getByRole('button', { name: 'Zigbee' })).toBeVisible();
	await expect(sources.getByRole('button', { name: 'Device simulator' })).toBeVisible();
	await expect(sources.getByRole('button', { name: 'Service' })).toHaveCount(0);
	await expect(page.locator('a[href$="/devices/openmeteo-weather"]')).toHaveCount(0);
	await expect(page.locator('a[href$="/devices/safety-safety"]')).toHaveCount(0);
	await sources.getByRole('button', { name: 'Device simulator' }).click();
	await expect(page.locator('tbody tr')).toHaveCount(4);
	await tabs.getByRole('button', { name: /Services/ }).click();
	await expect(page).toHaveURL(/tab=services/);
	await expect(page.locator('a[href$="/devices/openmeteo-weather"]')).toBeVisible();
	await expect(page.locator('a[href$="/devices/safety-safety"]')).toBeVisible();
	await page.goto('/en/extensions?open=fi.valo.openmeteo');
	await expect(page.locator('.card.ext', { hasText: 'Open-Meteo' })).toContainText('Adds: 2 services');
	await page.getByRole('dialog').getByRole('link', { name: '2 services' }).click();
	await expect(page).toHaveURL(/\/en\/devices\?tab=services&ext=fi\.valo\.openmeteo/);
	await expect(page.locator('tbody tr')).toHaveCount(2);
});

test('cameras show snapshot tiles, live video, events and recordings', async ({ page }) => {
	const errors = watchErrors(page);
	await login(page);
	await page.goto('/en/cameras');
	const tiles = page.locator('a.cam-tile');
	await expect(tiles).toHaveCount(2);
	await expect(tiles.first().locator('img')).toBeVisible({ timeout: 15000 });
	expect(await tiles.first().locator('img').evaluate((i) => i.naturalWidth)).toBeGreaterThan(0);
	await page.getByRole('button', { name: 'Storage' }).click();
	await expect(page.getByRole('dialog')).toContainText('valo-media');
	await page.keyboard.press('Escape');
	await page.goto('/en/cameras/dvor');
	await expect(page.locator('h1')).toHaveText('Двор');
	await expect.poll(() => page.locator('valo-video video').evaluate((v) => v.readyState).catch(() => 0), { timeout: 20000 }).toBeGreaterThanOrEqual(2);
	await page.getByRole('button', { name: 'Recordings' }).click();
	await expect(page.locator('.cam-m').first()).toBeVisible({ timeout: 10000 });
	const clip = await page.request.get('/api/v1/media?camera=dvor&kind=video&limit=1');
	const [m] = await clip.json();
	if (m) {
		const r = await page.request.get(m.url, { headers: { Range: 'bytes=0-99' } });
		expect(r.status()).toBe(206);
	}
	await page.getByRole('button', { name: 'Select' }).click();
	await page.locator('.cam-m').first().click();
	await expect(page.locator('.cam-pickbar')).toContainText('Selected: 1');
	await page.getByRole('button', { name: 'Timeline' }).click();
	await expect(page.locator('.tl-bar')).toBeVisible();
	await page.goto('/en/cameras/prihozhaya/settings?tab=camera');
	await expect(page.getByText('Motion detection on the camera')).toBeVisible({ timeout: 15000 });
	await page.getByRole('button', { name: 'Maintenance' }).click();
	await page.getByRole('button', { name: 'Check now' }).click();
	await expect(page.locator('.cs-checks .ri').first()).toBeVisible({ timeout: 15000 });
	const st = await (await page.request.get('/api/v1/cameras/prihozhaya')).json();
	expect(st.status.code).toBe('ok');
	const denied = await page.request.get('/rtc/api/streams');
	expect(denied.status()).toBe(403);
	expect(errors.filter((e) => !e.includes('favicon') && !e.includes('e2e browser error probe'))).toEqual([]);
});
