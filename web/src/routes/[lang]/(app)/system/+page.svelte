<script>
	import { keepTab } from '#lib/tabs.js';
	import Pages from '#lib/components/Pages.svelte';
	import { page } from '$app/state';
	import { useApp } from '#lib/app.svelte.js';
	import { LANGS } from '#lib/i18n/index.js';
	import Icon from '#lib/components/Icon.svelte';
	import Hint from '#lib/components/Hint.svelte';
	import Modal from '#lib/components/Modal.svelte';

	const app = useApp();
	const { s, t, f } = app;
	const admin = app.can('admin');
	let tab = $state((admin && page.url.searchParams.get('tab')) || (admin ? 'home' : 'about'));
	$effect(() => keepTab(tab, admin ? 'home' : 'about'));
	let errs = $state(null);
	let home = $state({ ...s.home, settings: { pushLevels: ['crit'], historyDays: 10, z2mAlertMinutes: 3, autoBackup: true, lang: app.lang, ...s.home.settings } });
	let users = $state([]);
	const SIZE = 25;
	const pgs = $state({ users: 0, tokens: 0, backups: 0, errors: 0 });
	const slice = (list, k) => (list || []).slice(pgs[k] * SIZE, (pgs[k] + 1) * SIZE);
	let tokens = $state([]);
	let backups = $state([]);
	let sys = $state(null);
	let res = $state(null);
	let upd = $state(null);
	let um = $state();
	let uf = $state({});
	let tm = $state();
	let tf = $state({ name: '', scope: 'read', rooms: [], days: 90 });
	let issued = $state('');
	let sure = $state('');
	let ai = $state(null);
	let models = $state([]);
	let aiTest = $state(null);
	let aiBusy = $state('');
	async function saveAi() {
		const { keySet, apiKey, ...rest } = ai;
		const body = { ...rest, temperature: +rest.temperature, maxSteps: +rest.maxSteps, dailyLimit: +rest.dailyLimit, ...(apiKey ? { apiKey } : {}) };
		const r = await app.run(() => app.api('PATCH', '/ai/settings', body), t('sys.saved'));
		if (r) ai = { ...r, apiKey: '' };
	}
	async function clearAiKey() {
		const r = await app.run(() => app.api('PATCH', '/ai/settings', { apiKey: null }), t('sys.saved'));
		if (r) ai = { ...r, apiKey: '' };
	}
	async function loadModels() {
		aiBusy = 'models';
		models = (await app.run(() => app.api('GET', '/ai/models'))) || [];
		aiBusy = '';
	}
	async function testAi() {
		aiBusy = 'test';
		aiTest = null;
		try {
			aiTest = await app.api('POST', '/ai/test');
		} catch (e) {
			aiTest = { error: e.message };
		}
		aiBusy = '';
	}

	$effect(() => {
		const k = tab;
		const get = (p) =>
			app.api('GET', p).catch((e) => {
				console.warn('system load failed', p, e);
				return null;
			});
		if (k === 'users') get('/users').then((x) => (users = x || []));
		if (k === 'tokens') get('/tokens').then((x) => (tokens = x || []));
		if (k === 'backups') get('/system/backups').then((x) => (backups = x || []));
		if (k === 'errors') loadErrors();
		if (k === 'ai') get('/ai/settings').then((x) => x && (ai = { ...x, apiKey: '' }));
		if (k === 'about') Promise.all([get('/system'), admin ? get('/system/resources') : null, admin ? get('/system/update') : null]).then(([a, b, c]) => ([sys, res, upd] = [a, b, c]));
	});
	const saveHome = () =>
		app.run(() => app.api('PATCH', '/home', { name: home.name, lat: +home.lat, lon: +home.lon, timezone: home.timezone, currency: home.currency, settings: { ...home.settings, historyDays: +home.settings.historyDays, z2mAlertMinutes: +home.settings.z2mAlertMinutes } }), t('sys.saved'));
	function editUser(u) {
		uf = u ? { ...u, password: '' } : { username: '', name: '', password: '', role: 'member', rooms: [], lang: app.lang };
		sure = '';
		um.show();
	}
	async function saveUser() {
		const body = { name: uf.name, role: uf.role, rooms: uf.rooms, lang: uf.lang, ...(uf.password ? { password: uf.password } : {}) };
		const r = await app.run(() => (uf.id ? app.api('PATCH', `/users/${uf.id}`, { ...body, active: uf.active }) : app.api('POST', '/users', { ...body, username: uf.username.trim() })), t('sys.user_saved'));
		if (r) (um.hide(), (users = await app.api('GET', '/users')));
	}
	async function delUser() {
		if (sure !== uf.id) return void (sure = uf.id);
		if (await app.run(() => app.api('DELETE', `/users/${uf.id}`), t('sys.user_deleted'))) (um.hide(), (users = users.filter((x) => x.id !== uf.id)));
	}
	async function addToken() {
		const r = await app.run(() => app.api('POST', '/tokens', { ...tf, days: tf.days ? +tf.days : null }));
		if (r) ((issued = r.token), (tokens = [r.item, ...tokens]));
	}
	async function delToken(x) {
		if (sure !== x.id) return void (sure = x.id);
		if (await app.run(() => app.api('DELETE', `/tokens/${x.id}`), t('sys.token_deleted'))) tokens = tokens.filter((y) => y.id !== x.id);
	}
	async function backup() {
		if (await app.run(() => app.api('POST', '/system/backups'), t('sys.backup_started'))) setTimeout(async () => (backups = await app.api('GET', '/system/backups')), 2500);
	}
	let upload = $state();
	let uploading = $state(false);
	async function uploadBackup(e) {
		const file = e.currentTarget.files?.[0];
		e.currentTarget.value = '';
		if (!file) return;
		uploading = true;
		try {
			const r = await fetch('/api/v1/system/backups/upload', { method: 'POST', headers: { 'content-type': 'application/octet-stream', 'x-filename': encodeURIComponent(file.name) }, body: file });
			const data = await r.json().catch(() => null);
			if (!r.ok) throw new Error(data?.title || data?.detail || String(r.status));
			app.toast(t('sys.uploaded', { name: file.name }));
			backups = await app.api('GET', '/system/backups');
		} catch (err) {
			console.error('backup upload failed', err.message);
			app.toast(err.message, 'crit');
		} finally {
			uploading = false;
		}
	}
	async function restore(b) {
		if (sure !== `r${b.id}`) return void (sure = `r${b.id}`);
		await app.run(() => app.api('POST', `/system/backups/${b.id}/restore`), t('sys.restore_started'));
	}
	async function delBackup(b) {
		if (sure !== `d${b.id}`) return void (sure = `d${b.id}`);
		if (await app.run(() => app.api('DELETE', `/system/backups/${b.id}`))) backups = backups.filter((x) => x.id !== b.id);
	}
	async function loadErrors() {
		errs = await app.api('GET', '/system/errors').catch((e) => {
			console.warn('errors load failed', e);
			return errs;
		});
		if (errs?.unseen) app.api('POST', '/system/errors/seen').catch((e) => console.warn('errors seen failed', e));
	}
	async function clearErrors() {
		if (sure !== 'errors') return void (sure = 'errors');
		sure = '';
		if (await app.run(() => app.api('DELETE', '/system/errors'))) errs = { items: [], seen: 0, unseen: 0 };
	}
	const copy = (x) => navigator.clipboard?.writeText(x).then(() => app.toast(t('a.copied')));
	const zones = ['Europe/Helsinki', 'Europe/Stockholm', 'Europe/Oslo', 'Europe/Copenhagen', 'Europe/Tallinn', 'Europe/Riga', 'Europe/Vilnius', 'Europe/Berlin', 'Europe/Kyiv', 'Europe/Warsaw'];
	const pct = (a, b) => (b ? Math.round((100 * a) / b) : 0);
	const load = (v) => (v >= 90 ? 'color:var(--crit)' : v >= 80 ? 'color:var(--warn)' : '');
</script>

<svelte:head><title>{t('nav.system')} · valo</title></svelte:head>

<div class="ph"><div><h1>{t('nav.system')} <Hint k="p_system" doc="system" /></h1><p>{t('sys.sub')}</p></div></div>
<div class="sub">
	<nav class="subn" aria-label={t('nav.system')}>
		{#each [...(admin ? [['home', 'sys.t_home'], ['users', 'sys.t_users']] : []), ['tokens', 'sys.t_tokens'], ...(admin ? [['backups', 'sys.t_backups'], ['errors', 'sys.t_errors'], ['ai', 'sys.t_ai']] : []), ['about', 'sys.t_about']] as [k, l]}
			<button class:on={tab === k} onclick={() => (tab = k)}>{t(l)}</button>
		{/each}
	</nav>
	<div class="g" style="align-content:start">
		{#if tab === 'home'}
			<section class="card g" style="gap:14px">
				<div class="fg">
					<label class="f">{t('setup.home_name')}<input class="in" bind:value={home.name} /></label>
					<label class="f">{t('setup.lat')}<input class="in" type="number" step="any" bind:value={home.lat} /></label>
					<label class="f">{t('setup.lon')}<input class="in" type="number" step="any" bind:value={home.lon} /></label>
					<label class="f">{t('setup.tz')}<select class="in" bind:value={home.timezone}>{#each zones as z}<option>{z}</option>{/each}</select></label>
					<label class="f">{t('setup.currency')}<select class="in" bind:value={home.currency}>{#each ['EUR', 'SEK', 'NOK', 'DKK'] as c}<option>{c}</option>{/each}</select></label>
					<label class="f">{t('sys.lang')}<select class="in" bind:value={home.settings.lang}>{#each LANGS as l}<option value={l}>{t(`lang.${l}`)}</option>{/each}</select></label>
					<label class="f">{t('sys.history_days')}<input class="in" type="number" min="1" max="400" bind:value={home.settings.historyDays} /></label>
					<div class="f"><span><label for="z2m-alert">{t('sys.z2m_alert')}</label> <Hint k="sys_z2m_alert" doc="system" /></span><input id="z2m-alert" class="in" type="number" min="0" max="60" bind:value={home.settings.z2mAlertMinutes} /></div>
				</div>
				<div class="f">{t('sys.push_levels')}
					<div class="seg">{#each ['info', 'warn', 'crit'] as l}<button class:on={home.settings.pushLevels.includes(l)} aria-pressed={!!(home.settings.pushLevels.includes(l))} onclick={() => (home.settings.pushLevels = home.settings.pushLevels.includes(l) ? home.settings.pushLevels.filter((x) => x !== l) : [...home.settings.pushLevels, l])}>{t(`lvl.${l}`)}</button>{/each}</div>
				</div>
				<label class="row sm"><input type="checkbox" bind:checked={home.settings.autoBackup} />{t('sys.auto_backup')}</label>
				<div><button class="btn pri" onclick={saveHome}>{t('a.save')}</button></div>
			</section>
		{:else if tab === 'users'}
			<div class="row"><span class="sp"></span><button class="btn pri" onclick={() => editUser(null)}><Icon name="plus" size={16} />{t('sys.add_user')}</button></div>
			<div class="tw">
				<table class="t-users">
					<thead><tr><th>{t('setup.owner_name')}</th><th>{t('login.user')}</th><th>{t('sys.role')} <Hint k="sys_roles" doc="system" /></th><th>{t('nav.rooms')}</th><th>{t('sys.last_login')}</th></tr></thead>
					<tbody>
						{#each slice(users, 'users') as u (u.id)}
							<tr>
								<td><button class="cellbtn" onclick={() => editUser(u)}>{u.name}</button>{#if !u.active} <span class="chip">{t('sys.disabled')}</span>{/if}</td><td class="mono sm">{u.username}</td>
								<td><span class="chip {u.role === 'owner' ? 'amber' : ''}">{t(`role.${u.role}`)}</span></td>
								<td class="dim sm">{u.rooms.length ? u.rooms.map((r) => s.rooms.find((x) => x.id === r)?.name ?? r).join(', ') : t('sys.all_rooms')}</td>
								<td class="dim sm">{f.ago(u.lastLoginAt)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			<Pages total={users.length} size={SIZE} bind:page={pgs.users} />
		{:else if tab === 'ai'}
			{#if ai}
				<section class="card g" style="gap:14px">
					<h3><Icon name="spark" size={16} />{t('ai.settings')} <Hint k="sys_ai" doc="assistant" /></h3>
					<p class="sm dim" style="margin:0">{t('ai.settings_hint')}</p>
					<label class="row sm"><input type="checkbox" bind:checked={ai.enabled} />{t('ai.enabled')}</label>
					<div class="fg" style="align-items:start">
						<label class="f">{t('ai.base_url')}<input class="in" bind:value={ai.baseUrl} /></label>
						<label class="f">{t('ai.model')}
							<input class="in" list="ai-models" bind:value={ai.model} />
							<datalist id="ai-models">{#each models as m (m.id)}<option value={m.id}>{m.name}</option>{/each}</datalist>
						</label>
						<label class="f">{t('ai.key')}
							<input class="in" type="password" autocomplete="off" bind:value={ai.apiKey} placeholder={ai.keySet ? t('ai.key_set') : t('ai.key_hint')} />
							{#if ai.keySet}<small class="dim">{t('ext.secret_set')}</small>{/if}
						</label>
						<label class="f">{t('ai.temperature')}<input class="in" type="number" min="0" max="2" step="0.1" bind:value={ai.temperature} /></label>
						<label class="f">{t('ai.max_steps')}<input class="in" type="number" min="1" max="30" bind:value={ai.maxSteps} /></label>
						<label class="f">{t('ai.daily_limit')}<input class="in" type="number" min="0" bind:value={ai.dailyLimit} /><small class="dim">{t('ai.daily_hint')}</small></label>
					</div>
					<div class="row">
						<button class="btn pri" onclick={saveAi}>{t('a.save')}</button>
						<button class="btn" disabled={!ai.keySet || !!aiBusy} onclick={testAi}>{aiBusy === 'test' ? '...' : t('ai.test')}</button>
						<button class="btn" disabled={!ai.keySet || !!aiBusy} onclick={loadModels}>{aiBusy === 'models' ? '...' : t('ai.load_models')}</button>
						{#if ai.keySet}<button class="btn ghost danger" onclick={clearAiKey}><Icon name="trash" size={16} />{t('ai.key_clear')}</button>{/if}
					</div>
					{#if models.length}<p class="sm dim" style="margin:0">{t('ai.models_n', { n: models.length })}</p>{/if}
					{#if aiTest}
						{#if aiTest.error}<p class="sm" style="margin:0;color:var(--crit)" role="alert">{aiTest.error}</p>
						{:else}<p class="sm" style="margin:0;color:var(--ok)">{t('ai.test_ok', { model: aiTest.model, reply: aiTest.reply, n: aiTest.usage?.total ?? '-' })}</p>{/if}
					{/if}
				</section>
			{:else}<p class="dim">{t('w.loading')}</p>{/if}
		{:else if tab === 'tokens'}
			<section class="card g" style="gap:12px">
				<h3><Icon name="key" size={16} />{t('sys.new_token')} <Hint k="sys_tokens" doc="system" /></h3>
				<div class="fg">
					<label class="f">{t('devs.name')}<input class="in" bind:value={tf.name} /></label>
					<label class="f">{t('sys.scope')}<select class="in" bind:value={tf.scope}><option value="read">{t('scope.read')}</option><option value="control">{t('scope.control')}</option></select></label>
					<label class="f">{t('sys.days')}<input class="in" type="number" min="0" bind:value={tf.days} /></label>
				</div>
				<div class="f">{t('nav.rooms')}<div class="seg" style="flex-wrap:wrap">{#each s.rooms as r (r.id)}<button class:on={tf.rooms.includes(r.id)} aria-pressed={!!(tf.rooms.includes(r.id))} onclick={() => (tf.rooms = tf.rooms.includes(r.id) ? tf.rooms.filter((x) => x !== r.id) : [...tf.rooms, r.id])}>{r.name}</button>{/each}</div></div>
				<div><button class="btn pri" disabled={!tf.name.trim()} onclick={addToken}>{t('a.create')}</button></div>
				{#if issued}<div class="row"><code class="mono" style="word-break:break-all;flex:1">{issued}</code><button class="btn s" onclick={() => copy(issued)}><Icon name="copy" size={14} />{t('a.copy')}</button></div><p class="sm" style="margin:0;color:var(--warn)">{t('sys.token_once')}</p>{/if}
			</section>
			<div class="tw">
				<table class="t-tokens">
					<thead><tr><th>{t('devs.name')}</th><th>{t('sys.scope')}</th><th>{t('nav.rooms')}</th><th>{t('sys.expires')}</th><th>{t('sys.used')}</th><th></th></tr></thead>
					<tbody>
						{#each slice(tokens, 'tokens') as x (x.id)}
							<tr>
								<td>{x.name}</td><td><span class="chip">{t(`scope.${x.scope}`)}</span></td>
								<td class="dim sm">{x.rooms.length ? x.rooms.map((r) => s.rooms.find((y) => y.id === r)?.name ?? r).join(', ') : t('sys.all_rooms')}</td>
								<td class="dim sm">{x.expiresAt ? f.date(x.expiresAt) : t('sys.never')}{#if x.expiresAt && new Date(x.expiresAt) < new Date()} <span class="chip crit">{t('sys.expired')}</span>{/if}</td><td class="dim sm">{f.ago(x.lastUsedAt)}</td>
								<td><button class="btn s danger" onclick={() => delToken(x)}>{sure === x.id ? t('a.confirm_delete') : t('a.delete')}</button></td>
							</tr>
						{:else}<tr><td colspan="6" class="dim">{t('sys.no_tokens')}</td></tr>{/each}
					</tbody>
				</table>
			</div>
			<Pages total={tokens.length} size={SIZE} bind:page={pgs.tokens} />
		{:else if tab === 'errors'}
			<div class="row">
				<p class="dim" style="margin:0">{t('sys.errors_hint')}</p>
				<button class="btn" onclick={loadErrors}><Icon name="refresh" size={16} />{t('a.refresh')}</button>
				{#if errs?.items.length}<button class="btn danger" onclick={clearErrors}><Icon name="trash" size={16} />{sure === 'errors' ? t('a.confirm_delete') : t('sys.errors_clear')}</button>{/if}
			</div>
			{#each slice(errs?.items, 'errors') as e (e.id)}
				<details class="card" style="padding:10px 14px">
					<summary class="row" style="cursor:pointer;gap:10px">
						<span class="chip {e.last > errs.seen ? 'crit' : ''}">{e.process}</span>
						<b style="font-weight:500;flex:1 1 220px;min-width:0;overflow-wrap:break-word">{e.event}</b>
						{#if e.count > 1}<span class="chip m">{t('sys.errors_count', { n: e.count })}</span>{/if}
						<span class="mono sm dim">{f.stamp(e.last)}</span>
					</summary>
					<dl class="kv" style="margin-top:10px">
						<dt>{t('sys.errors_source')}</dt><dd class="mono sm">{e.logger}</dd>
						<dt>{t('sys.errors_first')}</dt><dd class="mono sm">{f.stamp(e.first)}</dd>
					</dl>
					{#if e.detail}<pre class="mono sm" style="white-space:pre-wrap;overflow-wrap:anywhere;margin:8px 0 0">{e.detail}</pre>{/if}
					{#if e.trace}<pre class="mono sm" style="white-space:pre-wrap;overflow-wrap:anywhere;max-height:320px;overflow:auto;margin:8px 0 0">{e.trace}</pre>{/if}
				</details>
			{:else}<p class="dim">{errs ? t('sys.errors_empty') : t('w.loading')}</p>{/each}
			<Pages total={errs?.items.length || 0} size={SIZE} bind:page={pgs.errors} />
		{:else if tab === 'backups'}
			<div class="row"><p class="dim" style="margin:0">{t('sys.backup_hint')} <Hint k="sys_backups" doc="system" /></p>{#if app.can('owner')}<input type="file" accept=".gz,.tgz,application/gzip" hidden bind:this={upload} onchange={uploadBackup} /><button class="btn" disabled={uploading} onclick={() => upload.click()}><Icon name="download" size={16} />{uploading ? t('sys.uploading') : t('sys.upload_backup')}</button>{/if}<button class="btn pri" onclick={backup}><Icon name="upload" size={16} />{t('sys.backup_now')}</button></div>
			<p class="sm dim" style="margin:0">{t('sys.upload_hint')}</p>
			<div class="tw">
				<table>
					<thead><tr><th>{t('dev.when')}</th><th class="hm">{t('sys.kind')}</th><th>{t('dev.status')}</th><th class="hm">{t('sys.size')}</th><th></th></tr></thead>
					<tbody>
						{#each slice(backups, 'backups') as b (b.id)}
							<tr>
								<td class="mono sm">{f.stamp(b.createdAt)}</td><td class="hm">{t(`bk_kind.${b.kind}`)}</td>
								<td>
									<span class="chip {b.status === 'ok' ? 'ok' : b.status === 'failed' ? 'crit' : 'amber'}">{t(`bs.${b.status}`)}</span>
									{#if b.note?.includes('mirror:failed')}<span class="chip amber">{t('sys.mirror_failed')}</span>{/if}
									{#if b.status === 'failed' && b.note}<small class="dim" style="display:block">{b.note}</small>{/if}
								</td>
								<td class="num hm">{b.size ? f.bytes(b.size) : '-'}</td>
								<td><div class="row" style="justify-content:flex-end;flex-wrap:nowrap;gap:6px">
									{#if b.status === 'ok'}
										<a class="btn s" href="/api/v1/system/backups/{b.id}/download" title={t('a.download')} aria-label={t('a.download')}><Icon name="download" size={14} /><span class="bt">{t('a.download')}</span></a>
										{#if app.can('owner')}<button class="btn s" title={t('a.restore')} aria-label={sure === `r${b.id}` ? t('sys.confirm_restore') : t('a.restore')} onclick={() => restore(b)}><Icon name="refresh" size={14} /><span class="bt">{sure === `r${b.id}` ? t('sys.confirm_restore') : t('a.restore')}</span></button>{/if}
									{/if}
									<button class="btn s danger" title={t('a.delete')} aria-label={sure === `d${b.id}` ? t('a.confirm_delete') : t('a.delete')} onclick={() => delBackup(b)}><Icon name="trash" size={14} /><span class="bt">{sure === `d${b.id}` ? t('a.confirm_delete') : t('a.delete')}</span></button>
								</div></td>
							</tr>
						{:else}<tr><td colspan="5" class="dim">{t('sys.no_backups')}</td></tr>{/each}
					</tbody>
				</table>
			</div>
			<Pages total={backups.length} size={SIZE} bind:page={pgs.backups} />
		{:else}
			{#if sys}
				<section class="card">
					<h3><Icon name="cpu" size={16} />{t('sys.versions')}</h3>
					<dl class="kv">{#each Object.entries(sys.versions) as [k, v]}<dt>{t(`ver.${k}`)}</dt><dd class="mono sm">{v ? String(v).replace(/^mosquitto version /, '') : '-'}</dd>{/each}</dl>
				</section>
				<section class="card">
					<h3><Icon name="shield" size={16} />{t('sys.health')}</h3>
					<div class="lst">{#each Object.entries(sys.health) as [k, v]}{@const ok = v === true || v === 'online'}<div class="ri"><i class="dot" class:crit={!ok}></i><span style="flex:1">{t(`svc.${k}`)}</span><small>{typeof v === 'string' ? t(`zs.${v}`) : ok ? t('h.ok') : t('h.offline')}</small></div>{/each}</div>
				</section>
			{/if}
			{#if res}
				<section class="card">
					<h3><Icon name="chart" size={16} />{t('sys.resources')}</h3>
					<div class="big">
						<div><span class="lbl">CPU</span><b>{f.n(res.cpu, 0)}<small>%</small></b></div>
						<div><span class="lbl">{t('sys.memory')}</span><b style={load(pct(res.memory.total - res.memory.available, res.memory.total))}>{pct(res.memory.total - res.memory.available, res.memory.total)}<small>%</small></b></div>
						<div><span class="lbl">{t('sys.disk')}</span><b style={load(pct(res.disk.total - res.disk.free, res.disk.total))}>{pct(res.disk.total - res.disk.free, res.disk.total)}<small>%</small></b></div>
						<div><span class="lbl">{t('sys.db')}</span><b>{f.bytes(res.db)}</b></div>
						<div><span class="lbl">{t('sys.uptime')}</span><b>{f.n(res.uptime / 86400, 1)}<small>{t('sys.days_short')}</small></b></div>
					</div>
				</section>
			{/if}
			{#if upd}<section class="card"><h3><Icon name="refresh" size={16} />{t('sys.update')}</h3><p style="margin:0">{upd.latest && upd.latest !== upd.current ? t('sys.update_yes', { v: upd.latest }) : t('sys.update_no', { v: upd.current })}</p></section>{/if}
		{/if}
	</div>
</div>

<Modal bind:this={um} title={uf.id ? uf.name : t('sys.add_user')}>
	<div class="fg">
		<label class="f">{t('setup.owner_name')}<input class="in" bind:value={uf.name} autocomplete="name" /></label>
		<label class="f">{t('login.user')}<input class="in" bind:value={uf.username} disabled={!!uf.id} /></label>
		<label class="f">{t('login.password')}<input class="in" type="password" bind:value={uf.password} placeholder={uf.id ? t('sys.keep_password') : ''} autocomplete="new-password" /></label>
		<label class="f">{t('sys.role')}<select class="in" bind:value={uf.role} disabled={uf.role === 'owner' && !app.can('owner')}>{#each ['guest', 'member', 'admin', 'owner'] as r}<option value={r}>{t(`role.${r}`)}</option>{/each}</select></label>
		<label class="f">{t('sys.lang')}<select class="in" bind:value={uf.lang}>{#each LANGS as l}<option value={l}>{t(`lang.${l}`)}</option>{/each}</select></label>
	</div>
	<div class="f">{t('sys.rooms_access')}<div class="seg" style="flex-wrap:wrap">{#each s.rooms as r (r.id)}<button class:on={uf.rooms?.includes(r.id)} aria-pressed={!!(uf.rooms?.includes(r.id))} onclick={() => (uf.rooms = uf.rooms.includes(r.id) ? uf.rooms.filter((x) => x !== r.id) : [...uf.rooms, r.id])}>{r.name}</button>{/each}</div><span class="sm">{t('sys.rooms_hint')}</span></div>
	{#if uf.id}
		<label class="row sm"><input type="checkbox" bind:checked={uf.active} />{t('sys.active')}</label>
		{#if uf.id !== s.me.id}<div><button class="btn danger s" onclick={delUser}><Icon name="trash" size={14} />{sure === uf.id ? t('a.confirm_delete') : t('a.delete')}</button></div>{/if}
	{/if}
	{#snippet foot()}
		<button class="btn" onclick={() => um.hide()}>{t('a.cancel')}</button>
		<button class="btn pri" disabled={!uf.name?.trim() || (!uf.id && (!uf.username?.trim() || (uf.password || '').length < 6))} onclick={saveUser}>{t('a.save')}</button>
	{/snippet}
</Modal>
