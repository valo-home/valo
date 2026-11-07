<script>
	import Pages from '#lib/components/Pages.svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { useApp } from '#lib/app.svelte.js';
	import { icon, isOn, lowBat, primary } from '#lib/devices.js';
	import { keepTab } from '#lib/tabs.js';
	import Icon from '#lib/components/Icon.svelte';
	import Hint from '#lib/components/Hint.svelte';
	import Lqi from '#lib/components/Lqi.svelte';

	const app = useApp();
	const { s, t, f } = app;
	const MQTT = ['mqtt', 'ha', 'map'];
	let tab = $state(page.url.searchParams.get('tab') === 'services' ? 'services' : 'devices');
	let q = $state(page.url.searchParams.get('q') || '');
	let room = $state(page.url.searchParams.get('room') || '');
	let src = $state(page.url.searchParams.get('ext') ? `ext:${page.url.searchParams.get('ext')}` : '');
	let flag = $state('');
	$effect(() => keepTab(tab, 'devices'));
	const tx = (x) => (x && typeof x === 'object' ? (x[app.lang] ?? x.en ?? Object.values(x)[0]) : (x ?? ''));
	const extName = (id) => tx(s.contrib?.exts?.find((x) => x.id === id)?.name) || id || '-';
	const srcKey = (d) => (d.service ? `ext:${d.extId}` : d.source === 'ext' ? `ext:${d.extId}` : MQTT.includes(d.source) ? 'mqtt' : d.source);
	const srcName = (k) => (k.startsWith('ext:') ? extName(k.slice(4)) : t(`src.${k}`));
	const rooms = $derived(Object.fromEntries(s.rooms.map((r) => [r.id, r.name])));
	const all = $derived(Object.values(s.devices));
	const devs = $derived(all.filter((d) => !d.service));
	const svcs = $derived(all.filter((d) => d.service));
	const pool = $derived(tab === 'services' ? svcs : devs);
	const rank = (k) => ({ zigbee: 0, mqtt: 1 })[k] ?? 2;
	const sources = $derived([...new Set(pool.map(srcKey))].sort((a, b) => rank(a) - rank(b) || srcName(a).localeCompare(srcName(b))));
	$effect(() => {
		if (src && pool.length && !sources.includes(src)) src = '';
	});
	const list = $derived(
		pool
			.filter((d) => !q || `${d.name} ${d.model} ${d.id}`.toLowerCase().includes(q.toLowerCase()))
			.filter((d) => !room || (room === '-' ? !d.roomId : d.roomId === room))
			.filter((d) => !src || srcKey(d) === src)
			.filter((d) => tab === 'services' || !flag || (flag === 'offline' ? !d.available : flag === 'battery' ? lowBat(d) : flag === 'weak' ? d.attrs.lqi != null && d.attrs.lqi < 60 : true))
			.sort((a, b) => (tab === 'services' ? extName(a.extId).localeCompare(extName(b.extId)) : (rooms[a.roomId] || '~').localeCompare(rooms[b.roomId] || '~')) || a.name.localeCompare(b.name))
	);
	const SIZE = 50;
	let pg = $state(0);
	const shown = $derived(list.slice(pg * SIZE, (pg + 1) * SIZE));
	$effect(() => {
		tab, q, room, src, flag;
		pg = 0;
	});
	const open = (d) => goto(app.path(`/devices/${encodeURIComponent(d.id)}`));
</script>

<svelte:head><title>{t('nav.devices')} · valo</title></svelte:head>

<div class="ph">
	<div><h1>{t('nav.devices')} <Hint k="p_devices" doc="devices" /></h1><p>{t('devs.sub', { n: devs.length, svc: svcs.length, off: devs.filter((d) => !d.available).length })}</p></div>
</div>
<div class="tabs">
	<span class="th"><button class:on={tab === 'devices'} aria-pressed={tab === 'devices'} onclick={() => (tab = 'devices')}>{t('devs.t_devices')} <span class="cnt">{devs.length}</span></button><Hint k="dev_devices" doc="devices" /></span>
	<span class="th"><button class:on={tab === 'services'} aria-pressed={tab === 'services'} onclick={() => (tab = 'services')}>{t('devs.t_services')} <span class="cnt">{svcs.length}</span></button><Hint k="dev_services" doc="concepts" /></span>
</div>
<div class="row" style="margin-bottom:14px">
	<input class="in" style="max-width:280px" placeholder={t('a.search')} aria-label={t('a.search')} bind:value={q} />
	{#if tab === 'devices'}
		<select class="in" style="max-width:200px" bind:value={room} aria-label={t('devs.room')}>
			<option value="">{t('devs.all_rooms')}</option>
			{#each s.rooms as r (r.id)}<option value={r.id}>{r.name}</option>{/each}
			<option value="-">{t('devs.no_room')}</option>
		</select>
	{/if}
	{#if sources.length > 1}
		<div class="fl"><div class="seg" role="group" aria-label={tab === 'services' ? t('devs.ext') : t('devs.source')}>
			<button class:on={!src} aria-pressed={!src} onclick={() => (src = '')}>{tab === 'services' ? t('devs.all_ext') : t('devs.all')}</button>
			{#each sources as x (x)}<button class:on={src === x} aria-pressed={src === x} onclick={() => (src = x)}>{srcName(x)}</button>{/each}
		</div>
		{#if tab === 'devices'}<Hint k="dev_src" doc="devices" />{/if}</div>
	{/if}
	{#if tab === 'devices'}
		<div class="fl"><div class="seg" role="group" aria-label={t('devs.state')}>
			{#each [['', 'devs.any'], ['offline', 'devs.offline'], ['battery', 'devs.battery'], ['weak', 'devs.weak']] as [k, l]}<button class:on={flag === k} aria-pressed={flag === k} onclick={() => (flag = k)}>{t(l)}</button>{/each}
		</div>
		<Hint k="dev_flags" doc="devices" /></div>
	{/if}
</div>
<div class="tw">
	{#if tab === 'devices'}
		<table>
			<thead><tr><th>{t('devs.name')}</th><th class="hm">{t('devs.room')}</th><th>{t('devs.state')}</th><th class="hm">{t('devs.source')}</th><th class="hm">{t('devs.link')} <Hint k="dev_link" doc="zigbee" /></th><th class="hm">{t('devs.seen')}</th></tr></thead>
			<tbody>
				{#each shown as d (d.id)}
					<tr class="cl" onclick={() => open(d)}>
						<td><span class="row" style="flex-wrap:nowrap;gap:10px"><span class="dico" class:on={isOn(d)} style="width:28px;height:28px"><Icon name={icon(d)} size={15} /></span><a class="dn" href={app.path(`/devices/${encodeURIComponent(d.id)}`)}>{d.name}</a></span></td>
						<td class="dim hm">{rooms[d.roomId] || '-'}</td>
						<td>{primary(app, d)}{#if typeof d.state.bat === 'number'}<span class="bat" class:low={lowBat(d)} title={t('cap.bat')}><Icon name="battery" size={12} />{d.state.bat}%</span>{/if}</td>
						<td class="hm"><span class="chip {d.source === 'zigbee' ? 'z' : d.source === 'ext' ? '' : 'm'}">{srcName(srcKey(d))}</span>{#if d.source === 'ha' || d.source === 'map'}<small class="dim sm" style="display:block;margin-top:3px">{t(`src.${d.source}`)}</small>{/if}</td>
						<td class="hm">{#if !d.available}<span class="chip crit">{t('v.offline')}</span>{:else if d.attrs.lqi != null}<Lqi q={d.attrs.lqi} />{:else}<span class="dim sm">-</span>{/if}</td>
						<td class="dim sm hm">{f.ago(d.lastSeen)}</td>
					</tr>
				{:else}
					<tr><td colspan="6" class="dim">{t('devs.none')}</td></tr>
				{/each}
			</tbody>
		</table>
	{:else}
		<table>
			<thead><tr><th>{t('devs.name')}</th><th>{t('devs.state')}</th><th class="hm">{t('devs.ext')}</th><th class="hm">{t('devs.seen')}</th></tr></thead>
			<tbody>
				{#each shown as d (d.id)}
					<tr class="cl" onclick={() => open(d)}>
						<td><span class="row" style="flex-wrap:nowrap;gap:10px"><span class="dico" class:on={isOn(d)} style="width:28px;height:28px"><Icon name={icon(d)} size={15} /></span><a class="dn" href={app.path(`/devices/${encodeURIComponent(d.id)}`)}>{d.name}</a></span></td>
						<td>{primary(app, d)}{#if !d.available} <span class="chip crit">{t('v.offline')}</span>{/if}</td>
						<td class="hm"><a href={app.path(`/extensions?open=${d.extId}`)} onclick={(e) => e.stopPropagation()}>{extName(d.extId)}</a></td>
						<td class="dim sm hm">{f.ago(d.lastSeen)}</td>
					</tr>
				{:else}
					<tr><td colspan="4" class="dim">{t('devs.no_services')}</td></tr>
				{/each}
			</tbody>
		</table>
	{/if}
</div>
<Pages total={list.length} size={SIZE} bind:page={pg} />
