<script>
	import { useApp } from '#lib/app.svelte.js';
	import { isOn } from '#lib/devices.js';
	import DeviceRow from './DeviceRow.svelte';

	let { room } = $props();
	const app = useApp();
	const { s, t, f } = app;
	const ds = $derived(Object.values(s.devices).filter((d) => d.roomId === room.id).sort((a, b) => a.name.localeCompare(b.name)));
	const avg = (k) => {
		const vs = ds.filter((d) => d.source !== 'ext' && typeof d.state[k] === 'number' && (k !== 't' || d.kind !== 'trv')).map((d) => d.state[k]);
		return vs.length ? vs.reduce((a, b) => a + b, 0) / vs.length : null;
	};
	const temp = $derived(avg('t'));
	const hum = $derived(avg('h'));
	const lights = $derived(ds.filter((d) => d.kind === 'light'));
	const on = $derived(ds.filter((d) => d.available && d.caps.some((c) => c.id === 'on' && c.access.includes('w')) && isOn(d)));
	const off = () => on.forEach((d) => app.cmd(d.id, { on: false }));
</script>

<div class="wd">
	<div class="row" style="gap:18px;align-items:baseline">
		{#if temp != null}<b class="num wbig">{f.n(temp, 1)}<small>°C</small></b>{/if}
		{#if hum != null}<b class="num wbig">{f.n(hum, 0)}<small>%</small></b>{/if}
		{#if lights.length}<span class="sm dim">{t('home.lights')} {t('home.of', { a: lights.filter(isOn).length, b: lights.length })}</span>{/if}
	</div>
	<div class="lst">
		{#each ds.slice(0, 6) as d (d.id)}<DeviceRow {d} />{:else}<span class="dim sm">{t('rooms.empty')}</span>{/each}
	</div>
	<div class="row" style="justify-content:space-between">
		{#if ds.length > 6}<a class="sm" href={app.path(`/rooms?room=${room.id}`)}>{t('w.more', { n: ds.length - 6 })}</a>{:else}<span></span>{/if}
		{#if on.length}<button class="btn s" onclick={off}>{t('w.all_off')}</button>{/if}
	</div>
</div>
