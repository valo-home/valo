<script>
	import { onMount, untrack } from 'svelte';
	import { page } from '$app/state';
	import { useApp } from '#lib/app.svelte.js';
	import Icon from '#lib/components/Icon.svelte';
	import Hint from '#lib/components/Hint.svelte';
	import Markdown from '#lib/components/Markdown.svelte';
	import Modal from '#lib/components/Modal.svelte';

	const app = useApp();
	const { s, t, f } = app;
	let tab = $state('installed');
	let list = $state([]);
	let cat = $state([]);
	let cur = $state(null);
	let drawer = $state();
	let consent = $state();
	let pending = $state(null);
	let logs = $state([]);
	let form = $state({});
	let sure = $state(false);
	let docsModal = $state();
	let upModal = $state();
	const ids = (v) => String(v || '').split(/[\s,;]+/).filter(Boolean);
	const flip = (v, id, on) => [...ids(v).filter((x) => x !== id), ...(on ? [id] : [])].join(',');
	const pickDevs = (st) =>
		Object.values(s.devices)
			.filter((d) => !d.service && (!st.caps?.length || d.caps.some((c) => st.caps.includes(c.id) && (!st.access || c.access.includes(st.access)))))
			.sort((a, b) => a.name.localeCompare(b.name));
	const adds = (id) => {
		const ds = Object.values(s.devices).filter((d) => d.extId === id);
		const c = s.contrib || {};
		const e = c.exts?.find((x) => x.id === id) || {};
		return [
			['n_cameras', ds.filter((d) => d.kind === 'camera').length, '/cameras'],
			['n_devices', ds.filter((d) => !d.service && d.kind !== 'camera').length, `/devices?ext=${id}`],
			['n_services', ds.filter((d) => d.service).length, `/devices?tab=services&ext=${id}`],
			['n_pages', (c.pages || []).filter((x) => x.ext === id).length, (c.pages || []).find((x) => x.ext === id) ? `/x/${id}/${c.pages.find((x) => x.ext === id).key}` : null],
			['n_widgets', (c.widgets || []).filter((x) => x.ext === id).length, '/boards'],
			['n_blocks', e.blocks || 0, '/flows'],
			['n_templates', e.templates || 0, '/flows']
		].filter((x) => x[1] > 0);
	};
	const clearSecret = (key) => app.run(() => app.api('PATCH', `/extensions/${cur.id}/settings`, { values: { [key]: null } }), t('ext.saved'));
	async function upgrade() {
		const ok = await app.run(() => app.api('POST', `/extensions/${cur.id}/update`, { grants: cur.newPerms }), t('ext.op_update'));
		if (ok) upModal.hide();
	}
	let docs = $state({ id: '', title: '', text: '' });
	async function showDocs(id, name) {
		docs = { id, title: tx(name), text: '' };
		docsModal.show();
		const r = await app.api('GET', `/extensions/${encodeURIComponent(id)}/docs?lang=${app.lang}`).catch(() => null);
		docs = { ...docs, text: r?.text || t('ext.no_docs') };
	}
	const tx = (x) => (x && typeof x === 'object' ? (x[app.lang] ?? x.en ?? Object.values(x)[0]) : (x ?? ''));
	const chip = (st) => ({ running: 'ok', error: 'crit', stopped: '', installing: 'amber', updating: 'amber', starting: 'amber', removing: 'amber' })[st] ?? '';
	const perm = (p) => {
		const [k, x] = p.split(':');
		if (k === 'network.outbound' && x === '*') return t('perm.network.any');
		return t.has(`perm.${k}`) ? t(`perm.${k}`, { x: x ?? '' }) : p;
	};

	async function load() {
		[list, cat] = await Promise.all([app.api('GET', '/extensions'), app.api('GET', '/extensions/catalog')]).catch(() => [list, cat]);
		if (cur) cur = list.find((x) => x.id === cur.id) ?? null;
	}
	onMount(() => {
		load().then(() => (loaded = true));
		const offs = [
			app.on('ext', (x) => ((list = list.some((y) => y.id === x.id) ? list.map((y) => (y.id === x.id ? x : y)) : [...list, x]), cur?.id === x.id && (cur = x))),
			app.on('ext_gone', () => load())
		];
		return () => offs.forEach((fn) => fn());
	});
	let loaded = $state(false);
	let opened = '';
	$effect(() => {
		const o = page.url.searchParams.get('open') ?? '';
		if (!loaded || o === opened) return;
		opened = o;
		const x = o && list.find((y) => y.id === o);
		if (x) untrack(() => open(x));
	});
	const logId = $derived(cur && app.can('admin') ? cur.id : '');
	$effect(() => {
		if (!logId) return;
		const unsub = app.sub([`extlog:${logId}`]);
		const off = app.on('ext_log', (x) => x?.ext === logId && (logs = [...logs, x.line].slice(-500)));
		return () => (off(), unsub());
	});
	async function loadLogs() {
		if (app.can('admin')) logs = await app.api('GET', `/extensions/${cur.id}/logs`).catch(() => logs);
	}
	function open(x) {
		cur = x;
		form = { ...x.settings };
		sure = false;
		logs = [];
		loadLogs();
		drawer.show();
	}
	function ask(item, version) {
		pending = { ...item, version };
		consent.show();
	}
	async function install() {
		const m = pending.manifest;
		const ok = await app.run(() => app.api('POST', `/extensions/${pending.id}/install`, { grants: m.perms || [], version: pending.version || null }), t('ext.installing', { name: tx(m.name) }));
		if (ok) (consent.hide(), (tab = 'installed'), load());
	}
	const op = (o) => app.run(() => app.api('POST', `/extensions/${cur.id}/${o}`), t(`ext.op_${o}`));
	async function saveSettings() {
		const vals = Object.fromEntries((cur.manifest.settings || []).map((st) => [st.key, st.type === 'number' ? +form[st.key] : form[st.key]]));
		await app.run(() => app.api('PATCH', `/extensions/${cur.id}/settings`, { values: vals }), t('ext.saved'));
	}
	async function remove() {
		if (!sure) return void (sure = true);
		if (await app.run(() => app.api('DELETE', `/extensions/${cur.id}`), t('ext.removing'))) drawer.hide();
	}
</script>

<svelte:head><title>{t('nav.extensions')} · valo</title></svelte:head>

<div class="ph"><div><h1>{t('nav.extensions')} <Hint k="p_extensions" doc="extensions" /></h1><p>{t('ext.sub')}</p></div></div>
<div class="tabs">
	<button class:on={tab === 'installed'} onclick={() => (tab = 'installed')}>{t('ext.t_installed')} {list.length}</button>
	<button class:on={tab === 'catalog'} onclick={() => (tab = 'catalog')}>{t('ext.t_catalog')}</button>
</div>

{#if tab === 'installed'}
	<div class="g">
		{#each list as x (x.id)}
			<button class="card ext" style="text-align:left" onclick={() => open(x)}>
				<div class="exi"><Icon name={x.manifest.icon || 'ext'} /></div>
				<div style="min-width:0">
					<b style="font-weight:600">{tx(x.manifest.name)}</b> <span class="mono sm dim nobr">{x.version}</span>
					<div class="sm dim">{tx(x.manifest.description)}</div>
					{#if adds(x.id).length}<div class="sm" style="margin-top:4px">{t('ext.adds')}: {adds(x.id).map(([k, n]) => t(`ext.${k}`, { n })).join(', ')}</div>{/if}
					<div class="tags">
						<span class="chip {chip(x.status)}">{t(`es.${x.status}`)}</span>
						<span class="chip {x.trust === 'official' ? 'z' : x.trust === 'local' ? 'amber' : ''}">{t(`trust.${x.trust}`)}</span>
						{#if x.update}<span class="chip amber">{t('ext.update_to', { v: x.update })}</span>{/if}
						{#if x.error}<span class="chip crit" style="max-width:420px;overflow:hidden;text-overflow:ellipsis">{x.error}</span>{/if}
					</div>
				</div>
				<Icon name="chev" />
			</button>
		{:else}<div class="empty">{t('ext.none')}</div>{/each}
	</div>
{:else}
	<div class="g2">
		{#each cat as c (c.id)}
			{@const m = c.manifest}
			<section class="card ext cat">
				<div class="exi"><Icon name={m.icon || 'ext'} /></div>
				<div style="min-width:0">
					<b style="font-weight:600">{tx(m.name)}</b> <span class="mono sm dim nobr">{m.version}</span>
					<div class="sm dim">{tx(m.description)}</div>
					<div class="tags"><span class="chip {m.trust === 'official' ? 'z' : ''}">{t(`trust.${m.trust || 'community'}`)}</span>{#if m.author}<span class="chip">{m.author}</span>{/if}{#if m.type === 'z2m-converter'}<span class="chip z">{t('ext.converter')}</span>{/if}</div>
				</div>
				<div class="exa">
					<button class="btn s" onclick={() => showDocs(c.id, c.manifest.name)}><Icon name="log" size={14} />{t('ext.docs')}</button>
					{#if c.installed}<span class="chip ok">{t('ext.installed_v', { v: c.installed })}</span>
					{:else if app.can('admin')}<button class="btn s pri" onclick={() => ask(c)}>{t('a.install')}</button>{/if}
				</div>
			</section>
		{/each}
	</div>
{/if}

<Modal bind:this={consent} title={t('ext.consent', { name: tx(pending?.manifest?.name) })}>
	{#if pending}
		<p class="dim" style="margin:0">{t('ext.consent_hint')} <Hint k="ext_perms" doc="extensions" /></p>
		<div class="lst">{#each pending.manifest.perms || [] as p}<div class="ri"><Icon name="key" size={16} />{perm(p)}</div>{:else}<span class="dim sm">{t('ext.no_perms')}</span>{/each}</div>
		{#if pending.manifest.trust !== 'official'}<p class="sm" style="margin:0;color:var(--warn)">{t('ext.community_warn')}</p>{/if}
	{/if}
	{#snippet foot()}
		<button class="btn" onclick={() => consent.hide()}>{t('a.cancel')}</button>
		<button class="btn pri" onclick={install}>{t('ext.allow_install')}</button>
	{/snippet}
</Modal>

<Modal bind:this={drawer} kind="drawer" icon={cur?.manifest.icon || 'ext'} title={tx(cur?.manifest.name)} sub={cur ? `${cur.id} · ${cur.version}` : ''}>
	{#if cur}
		<div class="row">
			<span class="chip {chip(cur.status)}">{t(`es.${cur.status}`)}</span>
			{#if cur.proc}<span class="chip">PID {cur.proc.pid}</span>{#if cur.proc.mem}<span class="chip" title={t('ext.limit_hint')}>{f.n(cur.proc.mem, 1)}{#if cur.proc.limits} / {cur.proc.limits.mem}{/if} MB</span>{/if}{#if cur.proc.cpu != null}<span class="chip" title={t('ext.limit_hint')}>CPU {f.n(cur.proc.cpu, 1)}%{#if cur.proc.limits} / {cur.proc.limits.cpu}%{/if}</span>{/if}{/if}
			{#if cur.restarts}<span class="chip warn">{t('ext.restarts', { n: cur.restarts })}</span>{/if}
		</div>
		{#if cur.error}<pre class="code" style="color:var(--crit)">{cur.error}</pre>{/if}
		<div class="lbl">{t('ext.adds_title')}</div>
		<div class="lst">
			{#each adds(cur.id) as [k, n, href] (k)}{#if href}<a class="ri" href={app.path(href)} onclick={() => drawer.hide()}><span style="flex:1">{t(`ext.${k}`, { n })}</span><Icon name="chev" size={14} /></a>{:else}<div class="ri"><span>{t(`ext.${k}`, { n })}</span></div>{/if}{:else}<span class="dim sm">{t('ext.adds_none')}</span>{/each}
		</div>
		{#if app.can('admin')}
			<div class="row">
				<button class="btn s" onclick={() => showDocs(cur.id, cur.manifest.name)}><Icon name="log" size={14} />{t('ext.docs')}</button>
				<button class="btn s" onclick={() => op('toggle')}>{cur.enabled ? t('a.disable') : t('a.enable')}</button>
				<button class="btn s" disabled={!cur.enabled} onclick={() => op('restart')}><Icon name="refresh" size={14} />{t('a.restart')}</button>
				{#if cur.update}<button class="btn s pri" onclick={() => (cur.newPerms?.length ? upModal.show() : op('update'))}>{t('ext.update_to', { v: cur.update })}</button>{/if}
			</div>
		{/if}
		{#if cur.manifest.settings?.length}
			<div class="lbl">{t('ext.settings')}</div>
			{#each cur.manifest.settings as st (st.key)}
				<svelte:element this={st.type === 'devices' ? 'div' : 'label'} class="f">{t.has(`prm.${st.key}`) ? t(`prm.${st.key}`) : tx(st.name) || st.key}
					{#if st.type === 'devices'}
						<div class="lst" style="max-height:220px;overflow:auto" role="group" aria-label={t.has(`prm.${st.key}`) ? t(`prm.${st.key}`) : tx(st.name) || st.key}>
							{#each pickDevs(st) as d (d.id)}<label class="ri"><input type="checkbox" checked={ids(form[st.key]).includes(d.id)} disabled={!app.can('admin')} onchange={(e) => (form[st.key] = flip(form[st.key], d.id, e.target.checked))} /><span style="flex:1">{d.name}</span><small>{s.rooms.find((r) => r.id === d.roomId)?.name || ''}</small></label>{:else}<span class="dim sm">{t('devs.none')}</span>{/each}
						</div>
					{:else if st.type === 'select'}<select class="in" bind:value={form[st.key]} disabled={!app.can('admin')}>{#each st.options as o}<option value={o}>{t.has(`opt.${o}`) ? t(`opt.${o}`) : o}</option>{/each}</select>
					{:else if st.type === 'number'}<input class="in" type="number" step="any" bind:value={form[st.key]} disabled={!app.can('admin')} />
					{:else if st.type === 'device'}<select class="in" bind:value={form[st.key]} disabled={!app.can('admin')}><option value="">-</option>{#each Object.values(s.devices) as d (d.id)}<option value={d.id}>{d.name}</option>{/each}</select>
					{:else if st.type === 'textarea'}<textarea class="in" rows="4" style="height:auto;font-family:var(--f-m)" bind:value={form[st.key]} disabled={!app.can('admin')}></textarea>
					{:else}<input class="in" type={st.type === 'secret' ? 'password' : 'text'} placeholder={st.type === 'secret' ? (cur.secrets?.includes(st.key) ? t('ext.secret_set') : t('ext.secret_keep')) : ''} bind:value={form[st.key]} disabled={!app.can('admin')} />{/if}
					{#if st.hint || (st.type !== 'devices' && t.has(`prmh.${st.key}`))}<small class="dim">{st.hint ? tx(st.hint) : t(`prmh.${st.key}`)}</small>{/if}
					{#if st.type === 'secret' && cur.secrets?.includes(st.key) && app.can('admin')}<button type="button" class="btn s ghost" style="justify-self:start" onclick={() => clearSecret(st.key)}>{t('ext.secret_clear')}</button>{/if}
				</svelte:element>
			{/each}
			{#if app.can('admin')}<div><button class="btn s pri" onclick={saveSettings}>{t('a.save')}</button></div>{/if}
		{/if}
		<div class="lbl">{t('ext.perms')} <Hint k="ext_perms" doc="extensions" /></div>
		<div class="lst">{#each cur.grants as p}<div class="ri"><Icon name="key" size={16} />{perm(p)}</div>{:else}<span class="dim sm">{t('ext.no_perms')}</span>{/each}</div>
		{#if cur.manifest.blocks?.length}
			<div class="lbl">{t('ext.blocks')}</div>
			<div class="tags">{#each cur.manifest.blocks as b}<span class="chip m">{tx(b.name)}</span>{/each}</div>
		{/if}
		{#if app.can('admin')}
			<div class="lbl">{t('ext.logs')}</div>
			<div class="console">{#each logs.slice(-120) as l}<div class:e={/ERROR|Traceback|Error/.test(l)} class:w={/WARNING/.test(l)}>{l}</div>{:else}<span>-</span>{/each}</div>
			<div><button class="btn danger s" onclick={remove}><Icon name="trash" size={14} />{sure ? t('a.confirm_delete') : t('ext.remove')}</button></div>
		{/if}
	{/if}
</Modal>

<Modal bind:this={docsModal} title={docs.title} wide>
	{#if docs.text}<Markdown text={docs.text} />{:else}<p class="dim">...</p>{/if}
</Modal>

<Modal bind:this={upModal} title={t('ext.update_perms', { v: cur?.update ?? '' })}>
	<p class="dim" style="margin:0">{t('ext.update_perms_hint')}</p>
	<div class="lst">{#each cur?.newPerms || [] as p}<div class="ri"><Icon name="key" size={16} />{perm(p)}</div>{/each}</div>
	{#snippet foot()}
		<button class="btn" onclick={() => upModal.hide()}>{t('a.cancel')}</button>
		<button class="btn pri" onclick={upgrade}>{t('ext.allow_update')}</button>
	{/snippet}
</Modal>
