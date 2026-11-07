<script>
	import { keepTab } from '#lib/tabs.js';
	import { page } from '$app/state';
	import { powerName } from '#lib/devices.js';
	import Pages from '#lib/components/Pages.svelte';
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { useApp } from '#lib/app.svelte.js';
	import Icon from '#lib/components/Icon.svelte';
	import Hint from '#lib/components/Hint.svelte';
	import Lqi from '#lib/components/Lqi.svelte';
	import NetMap from '#lib/components/NetMap.svelte';

	const app = useApp();
	const { s, t, f } = app;
	let tab = $state(page.url.searchParams.get('tab') || 'map');
	$effect(() => keepTab(tab, 'map'));
	let info = $state(null);
	let rows = $state([]);
	const SIZE = 50;
	let pg = $state(0);
	const shownRows = $derived(rows.slice(pg * SIZE, (pg + 1) * SIZE));
	let map = $state(null);
	let busy = $state(false);
	let picked = $state(null);
	let channel = $state(20);
	let ad = $state(null);
	let pick = $state({ path: '', type: '' });
	async function loadAdapter() {
		if (!app.can('admin')) return;
		ad = await app.api('GET', '/zigbee/adapter').catch((e) => (console.warn('adapter load failed', e?.message), null));
		const cur = ad?.adapters.find((a) => a.path === ad.current?.path) || ad?.adapters[0];
		if (cur) pick = { path: cur.path, type: ad.current?.type || cur.type || 'ember' };
	}
	async function setAdapter() {
		const r = await app.run(() => app.api('POST', '/zigbee/adapter', pick), t('zb.adapter_saved'));
		if (r) ad = r;
	}
	$effect(() => {
		if (tab === 'net' && !ad) loadAdapter();
	});
	const pd = $derived(picked ? s.devices[picked] : null);
	const plink = $derived(picked ? (map?.data?.value?.links || []).filter((l) => (l.source?.ieeeAddr ?? l.sourceIeeeAddr) === picked) : []);

	async function load() {
		[info, rows, map] = await Promise.all([app.api('GET', '/zigbee'), app.api('GET', '/zigbee/health'), app.api('GET', '/zigbee/networkmap')]).catch((e) => (app.toast(e.message, 'crit'), [info, rows, map]));
		channel = info?.network?.channel ?? channel;
	}
	onMount(() => {
		load();
		const offs = [
			app.sub(['zigbee']),
			app.on('zigbee', (d) => {
				if (d?.type === 'networkmap') {
					busy = false;
					d.ok ? load() : app.toast(t('zb.map_failed'), 'crit');
				} else if (d?.type === 'state' || d?.type === 'info') load();
			})
		];
		return () => offs.forEach((fn) => fn());
	});
	async function scan() {
		busy = true;
		if (!(await app.run(() => app.api('POST', '/zigbee/networkmap'), t('zb.map_started')))) busy = false;
	}
	async function setChannel() {
		const r = await app.run(() => app.api('POST', '/zigbee/channel', { channel: +channel }));
		if (r) app.toast(r.restartRequired ? t('zb.channel_restart') : t('zb.channel_set'), 'warn');
	}
</script>

<svelte:head><title>Zigbee · valo</title></svelte:head>

<div class="ph">
	<div>
		<h1>Zigbee <Hint k="p_zigbee" doc="zigbee" /></h1>
		<p>{#if info}{t('zb.sub', { n: info.counts.devices, r: info.counts.routers, ch: info.network.channel ?? '-' })}{/if}</p>
	</div>
	<div class="row">
		<span class="chip {info?.state === 'online' ? 'ok' : 'crit'}">{t(`zs.${info?.state || 'unknown'}`)}</span>
	</div>
</div>
{#if info}
	<div class="big" style="margin-bottom:16px">
		<div><span class="lbl">{t('zb.devices')}</span><b>{info.counts.devices}</b></div>
		<div><span class="lbl">{t('zb.routers')}</span><b>{info.counts.routers}</b></div>
		<div><span class="lbl">{t('zb.weak')}</span><b>{info.counts.weak}</b></div>
		<div><span class="lbl">{t('zb.offline')}</span><b>{info.counts.offline}</b></div>
		<div><span class="lbl">{t('zb.ota_n')}</span><b>{info.counts.ota}</b></div>
	</div>
{/if}
<div class="tabs">
	{#each [['map', 'zb.t_map'], ['devices', 'zb.t_devices'], ['net', 'zb.t_net']] as [k, l]}<button class:on={tab === k} onclick={() => (tab = k)}>{t(l)}</button>{/each}
	<span class="th">{#if tab === 'map'}<Hint k="zb_map" doc="zigbee" />{:else}<Hint k="dev_link" doc="zigbee" />{/if}</span>
</div>

{#if tab === 'map'}
	<div class="home">
		<section class="card" style="padding:8px">
			<div class="row" style="padding:6px 8px">
				<span class="sm dim">{map?.ts ? t('zb.map_at', { v: f.stamp(map.ts) }) : t('zb.map_none')}</span><span class="sp"></span>
				<button class="btn s" disabled={busy} onclick={scan}><Icon name="refresh" size={14} />{busy ? t('zb.scanning') : t('zb.scan')}</button>
			</div>
			{#if map?.data?.value}<NetMap data={map.data.value} {picked} onpick={(id) => (picked = picked === id ? null : id)} />{:else}<div class="empty">{t('zb.map_hint')}</div>{/if}
			<div class="legend">
				<span><i class="dot" style="background:var(--amber)"></i>{t('zb.coord')}</span><span><i class="dot" style="background:var(--frost)"></i>{t('zb.t_Router')}</span><span><i class="dot off"></i>{t('zb.t_EndDevice')}</span>
				<span><i class="dot" style="background:var(--ok)"></i>LQI ≥ 120</span><span><i class="dot warn"></i>60-119</span><span><i class="dot crit"></i>&lt; 60</span>
			</div>
		</section>
		<aside class="card">
			{#if pd}
				<h3>{pd.name}</h3>
				<dl class="kv">
					<dt>IEEE</dt><dd class="mono sm">{pd.ieee}</dd>
					<dt>{t('zb.type')}</dt><dd>{t(`zb.t_${pd.attrs.type}`)}</dd>
					<dt>{t('zb.lqi')}</dt><dd>{#if pd.attrs.lqi != null}<Lqi q={pd.attrs.lqi} />{:else}-{/if}</dd>
					{#each plink as l}<dt>{t('zb.parent')}</dt><dd>{s.devices[l.target?.ieeeAddr ?? l.targetIeeeAddr]?.name || t('zb.coord')} ({l.lqi ?? l.linkquality})</dd>{/each}
				</dl>
				<a class="btn s" style="margin-top:12px" href={app.path(`/devices/${pd.id}`)}>{t('zb.open_device')}</a>
			{:else}
				<p class="dim sm" style="margin:0">{t('zb.pick_hint')}</p>
			{/if}
		</aside>
	</div>
{:else if tab === 'devices'}
	<div class="tw">
		<table class="t-zb">
			<thead><tr><th>{t('devs.name')}</th><th>{t('zb.type')}</th><th>{t('zb.lqi')}</th><th>{t('cap.bat')}</th><th>{t('zb.firmware')}</th><th>{t('zb.ota')}</th><th>{t('devs.seen')}</th></tr></thead>
			<tbody>
				{#each shownRows as r (r.id)}
					<tr class="cl" onclick={() => goto(app.path(`/devices/${r.id}`))}>
						<td><a class="dn" href={app.path(`/devices/${r.id}`)}>{r.name}</a>{#if !r.available} <span class="chip crit">{t('v.offline')}</span>{/if}</td>
						<td class="dim sm">{r.type ? t(`zb.t_${r.type}`) : '-'}</td>
						<td>{#if r.lqi != null}<Lqi q={r.lqi} />{:else}-{/if}</td>
						<td>{#if typeof r.battery === 'number'}<span class="bat" class:low={r.battery < 15}>{r.battery}%</span>{:else}<span class="dim sm">{powerName(t, r.power)}</span>{/if}</td>
						<td class="mono sm">{r.sw || '-'}</td>
						<td>{#if r.ota?.state === 'available'}<span class="chip amber">{r.ota.latest_version}</span>{:else if r.ota?.state === 'updating'}<span class="chip amber">{f.n(r.ota.progress, 0)}%</span>{:else}<span class="dim sm">-</span>{/if}</td>
						<td class="dim sm">{f.ago(r.lastSeen)}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
	<Pages total={rows.length} size={SIZE} bind:page={pg} />
{:else if info}
	<div class="g2">
		<section class="card">
			<h3><Icon name="cpu" size={16} />{t('zb.coord')}</h3>
			<dl class="kv">
				<dt>{t('zb.adapter')}</dt><dd>{info.coordinator.type || '-'} {info.coordinator.meta?.revision || ''}</dd>
				<dt>IEEE</dt><dd class="mono sm">{info.coordinator.ieee || '-'}</dd>
				<dt>{t('zb.port')}</dt><dd class="mono sm">{info.config?.serial?.port || '-'}</dd>
				<dt>Zigbee2MQTT</dt><dd>{info.version || '-'}</dd>
				<dt>PAN ID</dt><dd class="mono">{info.network.panId ?? '-'}</dd>
				<dt>{t('zb.channel')}</dt><dd>{info.network.channel ?? '-'}</dd>
			</dl>
		</section>
		{#if ad}
			<section class="card g" style="gap:12px;align-content:start">
				<h3><Icon name="zig" size={16} />{t('setup.adapter_title')}</h3>
				{#if ad.current?.source === 'env'}
					<p class="sm dim" style="margin:0">{t('setup.adapter_env', { path: ad.current.path })}</p>
				{:else if ad.adapters.length}
					<select class="in" bind:value={pick.path} onchange={() => (pick.type = ad.adapters.find((a) => a.path === pick.path)?.type || pick.type)} aria-label={t('setup.adapter_title')}>{#each ad.adapters as a (a.path)}<option value={a.path}>{a.name}</option>{/each}</select>
					<label class="f">{t('setup.adapter_type')}<select class="in" bind:value={pick.type}>{#each ad.types as k}<option value={k}>{t(`setup.at_${k}`)}</option>{/each}</select></label>
					<p class="sm dim" style="margin:0">{t('zb.adapter_hint')}</p>
					<div><button class="btn" onclick={setAdapter} disabled={!pick.path || (pick.path === ad.current?.path && pick.type === ad.current?.type)}>{t('a.apply')}</button></div>
				{:else}
					<p class="sm dim" style="margin:0">{t('setup.adapter_none')}</p>
				{/if}
			</section>
		{/if}
		{#if app.can('owner')}
			<section class="card g" style="gap:12px;align-content:start">
				<h3><Icon name="wifi" size={16} />{t('zb.channel')}</h3>
				<p class="sm dim" style="margin:0">{t('zb.channel_hint')}</p>
				<div class="row"><select class="in" style="max-width:120px" bind:value={channel}>{#each Array.from({ length: 16 }, (_, i) => i + 11) as c}<option value={c}>{c}</option>{/each}</select><button class="btn" onclick={setChannel}>{t('a.apply')}</button></div>
			</section>
		{/if}
	</div>
{/if}
