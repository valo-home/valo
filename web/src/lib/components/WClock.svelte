<script>
	import { onMount } from 'svelte';
	import { useApp } from '#lib/app.svelte.js';
	import { value } from '#lib/devices.js';

	const app = useApp();
	const { s, t, f } = app;
	let now = $state(Date.now());
	onMount(() => {
		const i = setInterval(() => (now = Date.now()), 15000);
		return () => clearInterval(i);
	});
	const devs = $derived(Object.values(s.devices).filter((d) => d.available));
	const weather = $derived(devs.filter((d) => d.kind === 'weather' && typeof d.state.t === 'number').sort((a, b) => (b.state.cond ? 1 : 0) - (a.state.cond ? 1 : 0))[0]);
	const outdoor = $derived(new Set(s.rooms.filter((r) => r.outdoor).map((r) => r.id)));
	const outside = $derived(weather ? null : devs.find((d) => d.kind === 'clim' && outdoor.has(d.roomId) && typeof d.state.t === 'number'));
	const cal = $derived(devs.find((d) => d.kind === 'calendar'));
	const alarms = $derived(devs.filter((d) => d.kind === 'clock' && d.state.on && d.state.next).map((d) => `${d.name} ${d.state.next}`));
</script>

<div class="wd">
	<b class="num" style="font-size:44px;font-weight:300;line-height:1">{f.time(now)}</b>
	<div class="dim fl1">{f.full(now)}</div>
	{#if weather}
		<div class="row" style="gap:10px;align-items:baseline"><b class="num" style="font-size:24px;font-weight:300">{f.n(weather.state.t, 1)}°</b>{#if weather.state.cond}<span>{value(app, weather, 'cond')}</span>{/if}{#if typeof weather.state.wind === 'number'}<span class="sm dim">{t('cap.wind')} {value(app, weather, 'wind')}</span>{/if}</div>
	{:else if outside}
		<div class="row" style="gap:10px;align-items:baseline"><b class="num" style="font-size:24px;font-weight:300">{f.n(outside.state.t, 1)}°</b><span class="sm dim">{t('w.outside')}</span></div>
	{/if}
	{#if cal}<div class="sm">{cal.state.event || cal.state.holiday || t(cal.state.workday === false ? 'v.dayoff' : 'v.workday')}</div>{/if}
	{#if alarms.length}<div class="sm dim">{t('w.alarm_next')} {alarms.join(', ')}</div>{/if}
</div>
