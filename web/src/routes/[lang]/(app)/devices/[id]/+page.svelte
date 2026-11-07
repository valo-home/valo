<script>
	import { pager } from '#lib/components/pager.svelte.js';
	import More from '#lib/components/More.svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { useApp } from '#lib/app.svelte.js';
	import { KINDS, boolLabels, capName, icon, isOn, powerName, primary } from '#lib/devices.js';
	import CapControl from '#lib/components/CapControl.svelte';
	import Chart from '#lib/components/Chart.svelte';
	import Feed from '#lib/components/Feed.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import Hint from '#lib/components/Hint.svelte';
	import Lqi from '#lib/components/Lqi.svelte';
	import Modal from '#lib/components/Modal.svelte';

	const app = useApp();
	const { s, t, f } = app;
	const extName = (id) => { const n = s.contrib?.exts?.find((x) => x.id === id)?.name; return (n && typeof n === 'object' ? (n[app.lang] ?? n.en ?? Object.values(n)[0]) : n) || id; };
	const id = $derived(page.params.id);
	const d = $derived(s.devices[id]);
	const room = $derived(s.rooms.find((r) => r.id === d?.roomId));
	const nums = $derived(d ? d.caps.filter((c) => c.type === 'num' || c.type === 'bool') : []);
	let cap = $state('');
	$effect(() => {
		id;
		cap = '';
	});
	let hours = $state(24);
	let hist = $state(null);
	let tab = $state('events');
	let extra = $state({ flows: [], topics: [] });
	let ota = $state(null);
	let edit = $state();
	let form = $state({ name: '', roomId: '', kind: '' });
	let sure = $state(false);
	let force = $state(false);
	const chartCap = $derived(cap || nums.find((c) => ['t', 'w', 'p', 'pos', 'bri', 'lux', 'h'].includes(c.id))?.id || nums[0]?.id || '');

	$effect(() => {
		if (!d || !chartCap) return;
		const [i, c, h] = [id, chartCap, hours];
		hist = { points: [] };
		app.api('GET', `/devices/${encodeURIComponent(i)}/history?cap=${encodeURIComponent(c)}&hours=${h}`)
			.then((r) => i === id && c === chartCap && (hist = r))
			.catch((e) => {
				console.warn('device history failed', i, c, e?.message);
				if (i === id) hist = { points: [] };
			});
	});
	const enc = () => encodeURIComponent(id);
	const evp = pager(app, (b, n) => `/devices/${enc()}/events?limit=${n}${b ? `&before=${b}` : ''}`, (x) => x.id, 50);
	const cmp = pager(app, (b, n) => `/devices/${enc()}/commands?limit=${n}${b ? `&before=${encodeURIComponent(b)}` : ''}`, (x) => `${x.createdAt}|${x.id}`, 30);
	$effect(() => {
		const i = id;
		extra = { flows: [], topics: [] };
		evp.reset();
		cmp.reset();
		ota = null;
		const e = encodeURIComponent(i);
		Promise.all([app.api('GET', `/devices/${e}/flows`), app.can('admin') ? app.api('GET', `/devices/${e}/topics`) : []])
			.then(([flows, topics]) => i === id && (extra = { ...extra, flows, topics }))
			.catch((err) => console.warn('device extras failed', err?.message));
		const offs = [
			app.sub([`dev:${i}`]),
			app.on('zigbee', (z) => z?.type === 'ota' && z.device === i && (ota = z.ota)),
			app.on('event', (ev) => ev.deviceId === i && evp.push(ev)),
			app.on('cmd', (c) => c.deviceId === i && cmp.push(c))
		];
		return () => offs.forEach((fn) => fn());
	});

	const series = $derived(
		hist?.kind === 'hourly' ? hist.points.map(([ts, mean, lo, hi]) => [ts, mean, lo, hi]) : (hist?.points || []).filter((p) => typeof p[1] === 'number')
	);
	const capObj = $derived(d?.caps.find((c) => c.id === chartCap));
	const up = $derived(ota || d?.attrs.ota);

	function openEdit() {
		form = { name: d.name, roomId: d.roomId || '', kind: d.kind };
		sure = false;
		edit.show();
	}
	async function save() {
		const body = { name: form.name.trim(), roomId: form.roomId || null, ...(form.kind !== d.kind ? { kind: form.kind } : {}) };
		if (await app.run(() => app.api('PATCH', `/devices/${encodeURIComponent(id)}`, body), t('dev.saved'))) edit.hide();
	}
	async function remove() {
		if (!sure) return void (sure = true);
		if (await app.run(() => app.api('DELETE', `/devices/${encodeURIComponent(id)}?force=${force}`), t('dev.removed'))) {
			edit.hide();
			goto(app.path('/devices'));
		}
	}
	let zbBusy = $state('');
	async function zb(action) {
		if (zbBusy) return;
		zbBusy = action;
		try {
			await app.run(() => app.api('POST', `/zigbee/devices/${encodeURIComponent(id)}/${action}`), t(`zb.${action}_sent`));
		} finally {
			zbBusy = '';
		}
	}
	async function otaCheck() {
		if (zbBusy) return;
		zbBusy = 'ota';
		try {
			const r = await app.run(() => app.api('POST', `/zigbee/devices/${encodeURIComponent(id)}/ota-check`));
			if (r) app.toast(r.update_available ? t('zb.ota_yes') : t('zb.ota_no'));
		} finally {
			zbBusy = '';
		}
	}
</script>

<svelte:head><title>{d?.name ?? t('dev.title')} · valo</title></svelte:head>

{#if !d}
	<div class="empty">{t('dev.missing')} <a href={app.path('/devices')}>{t('nav.devices')}</a></div>
{:else}
	<div class="ph">
		<div class="row" style="gap:14px;flex-wrap:nowrap;min-width:0">
			<a class="btn ghost" href={app.path('/devices')} aria-label={t('a.back')} title={t('nav.devices')}><Icon name="back" size={16} /></a>
			<div class="dico hd" class:on={isOn(d)} style="width:48px;height:48px;border-radius:14px"><Icon name={icon(d)} size={24} /></div>
			<div style="min-width:0">
				<h1>{d.name} <Hint k="p_device" doc="devices" /></h1>
				<p class="meta"><span>{room?.name || t('devs.no_room')}</span><span>{d.model || d.kind}</span><span class="chip {d.source === 'zigbee' ? 'z' : 'm'}">{d.service ? t('src.service') : d.source === 'ext' ? t('devs.ext') : ['ha', 'map'].includes(d.source) ? `MQTT · ${t(`src.${d.source}`)}` : t(`src.${d.source}`)}</span>{#if d.source === 'ext'}<a href={app.path(`/extensions?open=${d.extId}`)}>{extName(d.extId)}</a>{/if}{#if !d.available}<span class="chip crit">{t('v.offline')}</span>{/if}</p>
			</div>
		</div>
		{#if app.can('admin')}<button class="btn" onclick={openEdit}><Icon name="edit" size={16} />{t('a.edit')}</button>{/if}
	</div>

	<div class="g2">
		<section class="card g" style="gap:10px;align-content:start">
			<h3><Icon name="sliders" size={16} />{d.caps.some((c) => c.access.includes('w')) ? t('dev.control') : t('devs.state')}<span class="sp"></span><span class="dim sm">{primary(app, d)}</span></h3>
			{#each d.caps as c (c.id)}<CapControl {d} {c} />{:else}<p class="dim">{t('dev.no_caps')}</p>{/each}
			<div class="sm dim">{t('dev.seen', { v: f.ago(d.lastSeen) })}</div>
		</section>
		<section class="card" style="min-width:0">
			<h3 style="flex-wrap:wrap"><Icon name="chart" size={16} />{t('dev.history')}<span class="sp"></span>
				<div class="seg">{#each [[24, 'dev.h24'], [168, 'dev.d7'], [720, 'dev.d30']] as [h, l]}<button class:on={hours === h} aria-pressed={!!(hours === h)} onclick={() => (hours = h)}>{t(l)}</button>{/each}</div>
			</h3>
			{#if nums.length > 1}
				<div class="seg" style="margin-bottom:10px">{#each nums as c (c.id)}<button class:on={chartCap === c.id} aria-pressed={!!(chartCap === c.id)} onclick={() => (cap = c.id)}>{capName(t, c)}</button>{/each}</div>
			{/if}
			{#key `${chartCap}:${hours}`}<Chart points={series} step={capObj?.type === 'bool'} digits={capObj?.type === 'bool' ? 0 : 1} labels={capObj?.type === 'bool' ? boolLabels(t, capObj.id) : null} />{/key}
		</section>
	</div>

	{#if d.source === 'zigbee'}
		<section class="card" style="margin-top:16px">
			<h3><Icon name="zig" size={16} />Zigbee</h3>
			{#if app.can('admin')}
				<div class="row" style="flex-wrap:wrap;gap:6px;margin-bottom:12px">
					{#if d.attrs.otaSupported !== false}<button class="btn s" disabled={!!zbBusy} onclick={otaCheck}>{zbBusy === 'ota' ? t('zb.waiting') : t('zb.ota_check')}</button>{/if}
					<button class="btn s" disabled={!!zbBusy} onclick={() => zb('configure')}>{zbBusy === 'configure' ? t('zb.waiting') : t('zb.configure')}</button>
					<button class="btn s" disabled={!!zbBusy} onclick={() => zb('interview')}>{zbBusy === 'interview' ? t('zb.waiting') : t('zb.interview')}</button>
				</div>
			{/if}
			<div class="g2" style="column-gap:40px">
				<dl class="kv">
					<dt>IEEE</dt><dd class="mono">{d.ieee}</dd>
					<dt>{t('zb.nwk')}</dt><dd class="mono">{d.attrs.nwk ?? '-'}</dd>
					<dt>{t('zb.type')}</dt><dd>{d.attrs.type ? t(`zb.t_${d.attrs.type}`) : '-'}</dd>
					<dt>{t('zb.power')}</dt><dd>{powerName(t, d.attrs.power)}</dd>
				</dl>
				<dl class="kv">
					<dt>{t('zb.lqi')}</dt><dd>{#if d.attrs.lqi != null}<Lqi q={d.attrs.lqi} />{:else}-{/if}</dd>
					<dt>{t('zb.model')}</dt><dd>{d.model} {d.attrs.supported === false ? `(${t('zb.unsupported')})` : ''}</dd>
					<dt>{t('zb.firmware')}</dt><dd class="mono">{d.attrs.sw || '-'}</dd>
					<dt>{t('zb.ota')}</dt>
					<dd>
						{#if up?.state === 'updating'}{t('zb.ota_progress', { n: f.n(up.progress, 0) })}
						{:else if up?.state === 'available'}<span class="chip amber">{up.installed_version} → {up.latest_version}</span>
							{#if app.can('admin')}<button class="btn s pri" style="margin-left:8px" onclick={() => app.run(() => app.api('POST', `/zigbee/devices/${encodeURIComponent(id)}/ota-update`), t('zb.ota_started'))}>{t('a.update')}</button>{/if}
						{:else if d.attrs.otaSupported === false}<span class="dim">{t('zb.ota_unsupported')}</span>{:else}{t('zb.ota_none')}{/if}
					</dd>
				</dl>
			</div>
			{#if up?.state === 'updating'}<div class="bar" style="margin-top:12px"><i style="width:{up.progress}%"></i></div>{/if}
		</section>
	{/if}

	<div class="tabs" style="margin-top:20px">
		{#each [['events', 'dev.t_events'], ['commands', 'dev.t_commands'], ['flows', 'dev.t_flows'], ...(app.can('admin') ? [['topics', 'dev.t_topics']] : [])] as [k, l]}
			<button class:on={tab === k} onclick={() => (tab = k)}>{t(l)}</button>
		{/each}
	</div>
	{#if tab === 'events'}
		<section class="card"><Feed events={evp.st.items} limit={evp.st.items.length} /><More p={evp} /></section>
	{:else if tab === 'commands'}
		<div class="tw">
			<table>
				<thead><tr><th>{t('dev.when')}</th><th>{t('dev.values')}</th><th>{t('dev.status')}</th><th>{t('dev.who')}</th></tr></thead>
				<tbody>
					{#each cmp.st.items as c (c.id)}
						<tr>
							<td class="mono sm">{f.stamp(c.createdAt)}</td>
							<td>{Object.entries(c.values).map(([k, v]) => `${t.has(`cap.${k}`) ? t(`cap.${k}`) : k} ${typeof v === 'boolean' ? t(v ? 'v.on' : 'v.off') : f.n(v, Number.isInteger(v) ? 0 : 1)}`).join(', ')}</td>
							<td><span class="chip {c.status === 'ok' ? 'ok' : c.status === 'pending' ? 'amber' : 'crit'}">{t(`cs.${c.status}`)}</span></td>
							<td class="dim sm">{c.actor}</td>
						</tr>
					{:else}<tr><td colspan="4" class="dim">{t('dev.no_commands')}</td></tr>{/each}
				</tbody>
			</table>
		</div>
		<More p={cmp} />
	{:else if tab === 'flows'}
		<section class="card lst">
			{#each extra.flows as x (x.id)}
				<a class="ri" href={app.path(`/flows/${x.id}`)}><Icon name="flow" size={16} />{x.name}<small>{x.nodes.map((n) => t.has(`blk.${n}`) ? t(`blk.${n}`) : n).join(', ')}</small></a>
			{:else}<span class="dim">{t('rooms.noflows')}</span>{/each}
		</section>
	{:else}
		<div class="tw">
			<table>
				<thead><tr><th>{t('mq.topic')}</th><th>{t('mq.payload')}</th><th>{t('dev.when')}</th></tr></thead>
				<tbody>
					{#each extra.topics as x (x.t)}
						<tr><td class="mono sm">{x.t}{#if x.r} <span class="chip">retain</span>{/if}</td><td class="mono sm" style="max-width:520px;word-break:break-all">{x.p}</td><td class="mono sm">{f.sec(x.ts)}</td></tr>
					{:else}<tr><td colspan="3" class="dim">{t('mq.none')}</td></tr>{/each}
				</tbody>
			</table>
		</div>
	{/if}

	<Modal bind:this={edit} title={t('dev.settings')} sub={d.id}>
		<label class="f">{t('devs.name')}<input class="in" bind:value={form.name} /></label>
		<div class="fg">
			<label class="f">{t('devs.room')}
				<select class="in" bind:value={form.roomId}><option value="">{t('devs.no_room')}</option>{#each s.rooms as r (r.id)}<option value={r.id}>{r.name}</option>{/each}</select>
			</label>
			<label class="f">{t('dev.kind')}
				<select class="in" bind:value={form.kind}>{#each KINDS as k}<option value={k}>{t(`kind.${k}`)}</option>{/each}</select>
			</label>
		</div>
		<div class="card" style="background:var(--sunk);display:grid;gap:10px">
			<b style="font-weight:500">{t('dev.remove_title')}</b>
			<span class="sm dim">{t(d.source === 'zigbee' ? 'dev.remove_zigbee' : 'dev.remove_other')}</span>
			{#if d.source === 'zigbee'}<label class="row sm"><input type="checkbox" bind:checked={force} />{t('dev.force')}</label>{/if}
			<div><button class="btn danger" onclick={remove}><Icon name="trash" size={16} />{sure ? t('a.confirm_delete') : t('a.delete')}</button></div>
		</div>
		{#snippet foot()}
			<button class="btn" onclick={() => edit.hide()}>{t('a.cancel')}</button>
			<button class="btn pri" disabled={!form.name.trim()} onclick={save}>{t('a.save')}</button>
		{/snippet}
	</Modal>
{/if}
