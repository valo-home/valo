<script>
	import { onMount } from 'svelte';
	import { useApp } from '#lib/app.svelte.js';
	import { icon } from '#lib/devices.js';
	import Blocks from './Blocks.svelte';
	import CameraTile from './CameraTile.svelte';
	import DeviceRow from './DeviceRow.svelte';
	import Icon from './Icon.svelte';
	import WClock from './WClock.svelte';
	import WDevice from './WDevice.svelte';
	import WList from './WList.svelte';
	import WRoom from './WRoom.svelte';
	import WValue from './WValue.svelte';

	let { w, box = 0, onneed = null } = $props();
	const CHROME = 34;
	let inner = $state();
	let natural = $state(0);
	$effect(() => {
		if (!inner) return;
		let frame = 0;
		const measure = () => {
			frame = 0;
			if (!inner) return;
			let n = inner.offsetHeight;
			for (const g of inner.querySelectorAll('.grow')) n -= g.offsetHeight - +(g.dataset.base || 0);
			if (n === natural) return;
			natural = n;
			onneed?.(n + CHROME);
		};
		const ro = new ResizeObserver(() => frame || (frame = requestAnimationFrame(measure)));
		ro.observe(inner);
		return () => (ro.disconnect(), cancelAnimationFrame(frame));
	});
	const grow = $derived(box && natural ? Math.max(0, Math.min(480, box - CHROME - natural)) : 0);
	const app = useApp();
	const { s, t } = app;
	const devs = $derived(Object.values(s.devices));
	const d = $derived(w.device ? s.devices[w.device] : null);
	const contrib = $derived(w.type === 'ext' ? s.contrib?.widgets?.find((x) => x.ext === w.ext && x.key === w.key) : null);
	const tx = (x) => (x && typeof x === 'object' ? (x[app.lang] ?? x.en ?? Object.values(x)[0]) : (x ?? ''));
	let blocks = $state(null);
	let failed = $state(false);
	let frame = $state();
	async function act(key) {
		const r = await app.run(() => app.api('POST', `/extensions/${w.ext}/page/${w.key}`, { ...extParams(), action: key }));
		if (r?.blocks) blocks = r.blocks;
	}

	const extParams = () => ({ lang: app.lang, ...(w.place ? { place: $state.snapshot(w.place) } : {}) });
	let seq = 0;
	async function load() {
		if (contrib?.level !== 'declarative') return;
		const n = ++seq;
		const r = await app.api('POST', `/extensions/${w.ext}/page/${w.key}`, extParams()).catch((e) => {
			console.warn('widget page failed', w.ext, w.key, e?.message);
			return null;
		});
		if (n !== seq) return;
		failed = !r;
		if (r) blocks = r.blocks ?? null;
	}
	$effect(() => {
		w.place?.lat;
		w.place?.lon;
		if (contrib?.level === 'declarative') load();
	});
	onMount(() => {
		const off = app.on('ext_page', (e) => w.type === 'ext' && e?.ext === w.ext && e.keys?.includes(w.key) && load());
		const i = setInterval(load, 600000);
		return () => (off(), clearInterval(i));
	});
	$effect(() => {
		if (contrib?.level !== 'isolated' || !frame) return;
		let dev = null;
		const post = () => {
			const x = dev && devs.find((y) => y.extId === w.ext && y.address === dev);
			x && frame.contentWindow?.postMessage({ type: 'state', state: $state.snapshot(x.state), lang: app.lang }, '*');
		};
		const msg = (e) => e.source === frame.contentWindow && e.data?.type === 'ready' && ((dev = e.data.device), post());
		addEventListener('message', msg);
		const off = app.on('state', post);
		return () => (removeEventListener('message', msg), off());
	});
	const room = $derived(w.room ? s.rooms.find((r) => r.id === w.room) : d ? s.rooms.find((r) => r.id === d.roomId) : null);
	const DEVICE = ['sensor', 'plug', 'thermo', 'device', 'camera'];
	const ICON = { lights: 'bulb', scenes: 'layers', leaks: 'drop', doors: 'door', room: 'rooms', battery: 'battery', power: 'bolt', attention: 'warn', clock: 'clock', value: 'chart', chart: 'chart', ext: 'ext' };
	const title = $derived(
		w.title?.trim() ||
			(w.type === 'lights' || w.type === 'room' ? room?.name || t(`w.${w.type}`) : d ? d.name : contrib ? tx(contrib.name) : t(`w.${w.type}`))
	);
	const sub = $derived(w.type === 'ext' && w.place?.name ? w.place.name : (DEVICE.includes(w.type) || w.type === 'value' || w.type === 'chart') && room ? room.name : '');
</script>

<section class="card" class:iso={contrib?.level === 'isolated'}>
<div class="wi" bind:this={inner}>
	<h3><Icon name={d && DEVICE.includes(w.type) ? icon(d) : ICON[w.type] || 'grid'} size={16} /><span class="wt"><span>{title}</span>{#if sub}<small>{sub}</small>{/if}</span></h3>
	{#if w.type === 'lights'}
		<div class="lst">{#each devs.filter((x) => x.roomId === w.room && x.kind === 'light') as x (x.id)}<DeviceRow d={x} />{:else}<span class="dim sm">{t('w.empty')}</span>{/each}</div>
	{:else if w.type === 'scenes'}
		<div class="scenes">{#each s.scenes as x (x.id)}<button class="scene" onclick={() => app.run(() => app.api('POST', `/scenes/${x.id}/apply`), t('scenes.applied', { name: x.name }))}><Icon name={x.icon} /><span>{x.name}</span></button>{/each}</div>
	{:else if ['leaks', 'doors', 'battery', 'power', 'attention'].includes(w.type)}
		<WList type={w.type} />
	{:else if w.type === 'clock'}
		<WClock />
	{:else if w.type === 'room'}
		{#if room}<WRoom {room} />{:else}<span class="dim sm">{t('w.missing')}</span>{/if}
	{:else if w.type === 'ext'}
		{#if !contrib}<span class="dim sm">{t('w.ext_off')}</span> <a class="sm" href={app.path(`/extensions?open=${w.ext}`)}>{t('w.open_ext')}</a>
		{:else if contrib.level === 'isolated'}<iframe bind:this={frame} title={title} src="/api/v1/extensions/{w.ext}/ui/{contrib.entry}" sandbox="allow-scripts" style="width:100%;height:120px;border:0"></iframe>
		{:else if blocks}<Blocks {blocks} compact onaction={app.can('member') ? act : null} />{:else if failed}<span class="dim sm">{t('w.ext_error')}</span>{:else}<span class="dim sm">{t('w.loading')}</span>{/if}
	{:else if !d}
		<span class="dim sm">{t('w.missing')}</span>
	{:else if w.type === 'value' || w.type === 'chart'}
		<WValue {d} {w} {grow} />
	{:else}
		<WDevice {d} {grow} />
	{/if}
</div>
</section>
