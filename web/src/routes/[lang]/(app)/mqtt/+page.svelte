<script>
	import { keepTab } from '#lib/tabs.js';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import { useApp } from '#lib/app.svelte.js';
	import { KINDS } from '#lib/devices.js';
	import Icon from '#lib/components/Icon.svelte';
	import Hint from '#lib/components/Hint.svelte';

	const app = useApp();
	const { s, t, f } = app;
	let tab = $state(page.url.searchParams.get('tab') || 'explorer');
	$effect(() => keepTab(tab, 'explorer'));
	let topics = $state({});
	let q = $state('');
	let sel = $state('');
	let detail = $state(null);
	let recent = $state([]);
	let broker = $state(null);
	let disc = $state([]);
	let clients = $state(null);
	let pub = $state({ topic: '', payload: '', qos: 0, retain: false });
	let mp = $state({ id: '', name: '', roomId: '', kind: 'clim', caps: [{ id: 't', type: 'num', topic: '', path: '', unit: '°C', cmd: '' }] });
	const open = new SvelteSet(['hub', 'zigbee2mqtt', 'homeassistant']);

	const tree = $derived.by(() => {
		const root = { kids: {} };
		for (const tp of Object.keys(topics).sort()) {
			if (q && !tp.toLowerCase().includes(q.toLowerCase())) continue;
			let n = root;
			tp.split('/').forEach((part, i, a) => {
				const path = a.slice(0, i + 1).join('/');
				n = n.kids[part] ??= { path, name: part, kids: {}, n: 0 };
				n.n++;
			});
		}
		return root;
	});

	async function load() {
		const [tp, bk, rc] = await Promise.all([app.api('GET', '/mqtt/topics'), app.api('GET', '/mqtt'), app.api('GET', '/mqtt/recent?limit=80')]).catch((e) => (app.toast(e.message, 'crit'), [[], null, []]));
		topics = Object.fromEntries(tp.map((x) => [x.t, x]));
		[broker, recent] = [bk, rc];
	}
	async function pick(tp) {
		sel = tp;
		detail = await app.api('GET', `/mqtt/topic?t=${encodeURIComponent(tp)}`).catch((e) => (console.warn('mqtt topic failed', e?.message), null));
		pub.topic = tp;
	}
	onMount(() => {
		load();
		const offs = [
			app.sub(['mqtt']),
			app.on('mqtt', (m) => {
				if (m.gone) delete topics[m.t];
				else topics[m.t] = { ...(topics[m.t] || { n: 0 }), t: m.t, p: m.p, r: m.r, q: m.q, ts: m.ts, n: (topics[m.t]?.n || 0) + 1, fl: Date.now() };
				recent = [[m.ts, m.t, m.p, m.r], ...recent].slice(0, 80);
				if (m.t === sel && detail) detail = { ...detail, p: m.p, ts: m.ts, h: [[detail.ts, detail.p], ...(detail.h || [])].slice(0, 5) };
			})
		];
		return () => offs.forEach((fn) => fn());
	});
	$effect(() => {
		if (tab === 'discovery') app.api('GET', '/mqtt/discovery').then((x) => (disc = x)).catch((e) => app.toast(e.message, 'crit'));
		if (tab === 'clients') app.api('GET', '/mqtt/clients').then((x) => (clients = x)).catch((e) => app.toast(e.message, 'crit'));
	});
	const pretty = (p) => {
		try {
			return JSON.stringify(JSON.parse(p), null, 2);
		} catch {
			return p;
		}
	};
	const send = () => app.run(() => app.api('POST', '/mqtt/publish', { ...pub, qos: +pub.qos }), t('mq.sent'));
	async function drop(tp) {
		if (await app.run(() => app.api('DELETE', `/mqtt/discovery?t=${encodeURIComponent(tp)}`), t('mq.config_removed'))) disc = await app.api('GET', '/mqtt/discovery').catch((e) => (console.warn('discovery reload failed', e?.message), disc));
	}
	const BLANK = () => ({ id: '', name: '', roomId: '', kind: 'clim', caps: [{ id: 't', type: 'num', topic: '', path: '', unit: '°C', cmd: '' }] });
	let mapEdit = $state('');
	let mapSure = $state('');
	const maps = $derived(Object.values(s.devices).filter((d) => d.source === 'map').sort((a, b) => a.name.localeCompare(b.name)));
	async function addMap() {
		const caps = mp.caps.filter((c) => c.id && c.topic).map((c) => Object.fromEntries(Object.entries(c).filter(([, v]) => v !== '' && v != null)));
		if (await app.run(() => app.api('POST', '/devices/mapping', { ...mp, roomId: mp.roomId || null, caps }), t(mapEdit ? 'mq.map_saved' : 'mq.mapped'))) ((mp = BLANK()), (mapEdit = ''));
	}
	function editMap(d) {
		mapEdit = d.id;
		mp = { id: d.id, name: d.name, roomId: d.roomId || '', kind: d.kind, caps: (d.attrs.map || []).map((c) => ({ id: c.id, type: c.type, topic: c.topic || '', path: c.path || '', unit: c.unit || '', cmd: c.cmd || '' })) };
		if (!mp.caps.length) mp.caps = BLANK().caps;
	}
	async function dropMap(d) {
		if (mapSure !== d.id) return void (mapSure = d.id);
		mapSure = '';
		if (await app.run(() => app.api('DELETE', `/devices/${encodeURIComponent(d.id)}?force=false`), t('dev.removed')) && mapEdit === d.id) ((mp = BLANK()), (mapEdit = ''));
	}
	const limits = $state({});
</script>

<svelte:head><title>MQTT · valo</title></svelte:head>

{#snippet node(n, depth)}
	{@const kids = Object.values(n.kids)}
	{#each kids.slice(0, limits[n.path || ''] || 100) as k (k.path)}
		{@const leaf = topics[k.path]}
		<button class="tn" class:sel={sel === k.path} class:fl={leaf?.fl && Date.now() - leaf.fl < 1000} style="padding-left:{6 + depth * 14}px" onclick={() => (Object.keys(k.kids).length && (open.has(k.path) ? open.delete(k.path) : open.add(k.path)), leaf && pick(k.path))}>
			{#if Object.keys(k.kids).length}<Icon name={open.has(k.path) ? 'layers' : 'chev'} size={12} />{/if}
			{k.name}{#if Object.keys(k.kids).length}<span class="dim">({k.n})</span>{/if}
			{#if leaf}<span class="pv">{leaf.p}</span>{/if}
		</button>
		{#if open.has(k.path) || q}{@render node(k, depth + 1)}{/if}
	{/each}
	{#if kids.length > (limits[n.path || ''] || 100)}
		<button class="tn dim" style="padding-left:{6 + depth * 14}px" onclick={() => (limits[n.path || ''] = (limits[n.path || ''] || 100) + 100)}>{t('pg.more')} ({kids.length - (limits[n.path || ''] || 100)})</button>
	{/if}
{/snippet}

<div class="ph">
	<div><h1>MQTT <Hint k="p_mqtt" doc="mqtt" /></h1><p>{#if broker}{t('mq.sub', { n: broker.topics, c: broker.sys['clients/connected'] ?? '-', v: broker.sys.version?.replace('mosquitto version ', '') ?? '-' })}{/if}</p></div>
	<span class="chip {broker?.connected ? 'ok' : 'crit'}">{broker?.connected ? t('h.online') : t('h.offline')}</span>
</div>
<div class="tabs">
	{#each [['explorer', 'mq.t_explorer'], ['discovery', 'mq.t_discovery'], ['mapping', 'mq.t_mapping'], ['clients', 'mq.t_clients']] as [k, l]}<button class:on={tab === k} onclick={() => (tab = k)}>{t(l)}</button>{/each}
	{#if { mapping: 1, discovery: 1, clients: 1 }[tab]}<span class="th"><Hint k={`mq_${tab}`} doc="mqtt" /></span>{/if}
</div>

{#if tab === 'explorer'}
	<div class="mx">
		<section class="card">
			<input class="in" placeholder={t('mq.filter')} aria-label={t('mq.filter')} bind:value={q} style="margin-bottom:10px" />
			<div class="tree">{@render node(tree, 0)}</div>
		</section>
		<div class="g" style="align-content:start">
			<section class="card">
				<h3><Icon name="mqtt" size={16} /><span class="mono" style="word-break:break-all">{sel || t('mq.pick')}</span></h3>
				{#if detail}
					<div class="row sm dim" style="margin-bottom:10px"><span>{f.sec(detail.ts)}</span><span>QoS {detail.q}</span>{#if detail.r}<span class="chip">retain</span>{/if}<span>{t('mq.count', { n: detail.n })}</span></div>
					<pre class="code">{pretty(detail.p)}</pre>
					{#if detail.h?.length}
						<div class="lbl" style="margin:12px 0 6px">{t('mq.prev')}</div>
						<div class="mlog">{#each detail.h as [ts, p]}<div><span>{f.sec(ts)}</span><span>{p}</span></div>{/each}</div>
					{/if}
				{/if}
			</section>
			<section class="card g" style="gap:10px">
				<h3><Icon name="send" size={16} />{t('mq.publish')}</h3>
				<input class="in mono" placeholder={t('mq.topic')} aria-label={t('mq.topic')} bind:value={pub.topic} />
				<textarea class="in mono" rows="3" placeholder={t('mq.payload')} aria-label={t('mq.payload')} bind:value={pub.payload}></textarea>
				<div class="row">
					<select class="in" style="max-width:110px" bind:value={pub.qos} aria-label="QoS">{#each [0, 1, 2] as x}<option value={x}>QoS {x}</option>{/each}</select>
					<label class="row sm"><input type="checkbox" bind:checked={pub.retain} />retain</label>
					<span class="sp"></span><button class="btn pri" disabled={!pub.topic.trim()} onclick={send}>{t('mq.send')}</button>
				</div>
			</section>
			<section class="card">
				<h3><Icon name="log" size={16} />{t('mq.recent')}</h3>
				<div class="mlog">{#each recent as [ts, tp, p]}<div><span>{f.sec(ts)}</span><span><b>{tp}</b> {p}</span></div>{/each}</div>
			</section>
		</div>
	</div>
{:else if tab === 'discovery'}
	<div class="tw">
		<table>
			<thead><tr><th>{t('devs.name')}</th><th class="hm">{t('mq.origin')}</th><th>{t('mq.configs')}</th><th class="hm">{t('devs.seen')}</th></tr></thead>
			<tbody>
				{#each disc as x (x.device)}
					<tr>
						<td><a class="dn" href={app.path(`/devices/${x.device}`)}>{x.name}</a>{#if x.ghost} <span class="chip warn">{t('mq.ghost')}</span>{/if}</td>
						<td class="dim sm hm">{x.origin || '-'}</td>
						<td class="mono sm">{#each x.configs as c}<div class="row" style="gap:8px;flex-wrap:nowrap;margin:2px 0"><span style="flex:1;min-width:0;overflow-wrap:anywhere">{c}</span><button class="btn s danger" title={t('mq.remove_config')} aria-label={`${t('mq.remove_config')} ${c}`} onclick={() => drop(c)}><Icon name="trash" size={14} /></button></div>{/each}</td>
						<td class="dim sm hm">{f.ago(x.lastSeen)}</td>
					</tr>
				{:else}<tr><td colspan="4" class="dim">{t('mq.no_discovery')}</td></tr>{/each}
			</tbody>
		</table>
	</div>
{:else if tab === 'mapping'}
	<section class="card g" style="gap:10px;margin-bottom:16px">
		<h3><Icon name="link" size={16} />{t('mq.maps')}<span class="sp"></span><span class="dim sm">{maps.length}</span></h3>
		{#each maps as d (d.id)}
			<div class="row" style="gap:10px;flex-wrap:nowrap;border-top:1px solid var(--line);padding-top:10px">
				<div style="flex:1;min-width:0">
					<a class="dn" href={app.path(`/devices/${encodeURIComponent(d.id)}`)}>{d.name}</a>
					<div class="mono sm dim" style="overflow-wrap:anywhere">{(d.attrs.map || []).map((c) => `${c.id} ← ${c.topic}${c.path ? ` · ${c.path}` : ''}`).join('; ')}</div>
				</div>
				<button class="btn s" class:on={mapEdit === d.id} aria-label={t('a.edit')} title={t('a.edit')} onclick={() => editMap(d)}><Icon name="edit" size={14} /><span class="bt">{t('a.edit')}</span></button>
				<button class="btn s danger" aria-label={mapSure === d.id ? t('a.confirm_delete') : t('a.delete')} title={t('a.delete')} onclick={() => dropMap(d)}><Icon name="trash" size={14} /><span class="bt">{mapSure === d.id ? t('a.confirm_delete') : t('a.delete')}</span></button>
			</div>
		{:else}<p class="dim" style="margin:0">{t('mq.no_maps')}</p>{/each}
	</section>
	<section class="card g" style="gap:12px">
		<h3><Icon name={mapEdit ? 'edit' : 'plus'} size={16} />{mapEdit ? t('mq.map_edit', { name: mp.name }) : t('mq.map_new')}</h3>
		<p class="dim" style="margin:0">{t('mq.map_hint')}</p>
		<div class="fg">
			<label class="f">ID<input class="in mono" bind:value={mp.id} placeholder="garage-temp" disabled={!!mapEdit} /></label>
			<label class="f">{t('devs.name')}<input class="in" bind:value={mp.name} /></label>
			<label class="f">{t('devs.room')}<select class="in" bind:value={mp.roomId}><option value="">{t('devs.no_room')}</option>{#each s.rooms as r (r.id)}<option value={r.id}>{r.name}</option>{/each}</select></label>
			<label class="f">{t('mq.dtype')}<select class="in" bind:value={mp.kind}>{#each KINDS as k}<option value={k}>{t(`kind.${k}`)}</option>{/each}</select></label>
		</div>
		{#each mp.caps as c, i}
			<div class="fg" style="grid-template-columns:repeat(auto-fit,minmax(min(100%,180px),1fr))">
				<label class="f">{t('mq.cap')}<input class="in mono" bind:value={c.id} /></label>
				<label class="f">{t('mq.vtype')}<select class="in" bind:value={c.type}>{#each ['num', 'bool', 'text'] as x}<option value={x}>{t(`mq.vt_${x}`)}</option>{/each}</select></label>
				<label class="f">{t('mq.topic')}<input class="in mono" bind:value={c.topic} placeholder="garage/sensor/tele" /></label>
				<label class="f">{t('mq.path')}<input class="in mono" bind:value={c.path} placeholder="DS18B20.Temperature" /></label>
				<label class="f">{t('mq.unit')}<input class="in" bind:value={c.unit} /></label>
				<label class="f">{t('mq.cmd')}<input class="in mono" bind:value={c.cmd} /></label>
			</div>
			{#if i < mp.caps.length - 1}<div style="border-top:1px dashed var(--line)"></div>{/if}
		{/each}
		<div class="row">
			<button class="btn s" onclick={() => (mp.caps = [...mp.caps, { id: '', type: 'num', topic: mp.caps.at(-1)?.topic || '', path: '', unit: '', cmd: '' }])}><Icon name="plus" size={14} />{t('mq.add_cap')}</button>
			<span class="sp"></span>
			{#if mapEdit}<button class="btn" onclick={() => ((mp = BLANK()), (mapEdit = ''))}>{t('a.cancel')}</button>{/if}
			<button class="btn pri" disabled={!mp.id.trim() || !mp.name.trim()} onclick={addMap}>{mapEdit ? t('a.save') : t('a.create')}</button>
		</div>
	</section>
{:else}
	<div class="g2">
		<section class="card">
			<h3>{t('mq.clients')}</h3>
			<div class="lst mq">{#each clients?.clients || [] as c}<div class="ri"><Icon name="user" size={16} /><span class="mono" style="flex:1">{c.username}</span><small>{(c.roles || []).map((r) => r.rolename).join(', ')}</small></div>{/each}</div>
		</section>
		<section class="card">
			<h3>{t('mq.roles')}</h3>
			<div class="lst mq">{#each clients?.roles || [] as r}<details><summary class="ri"><Icon name="shield" size={16} /><span class="mono">{r.rolename}</span><small>{t('mq.rules', { n: r.acls?.length || 0 })}</small></summary><pre class="code">{(r.acls || []).map((a) => `${a.acltype} ${a.topic}`).join('\n')}</pre></details>{/each}</div>
		</section>
	</div>
{/if}
