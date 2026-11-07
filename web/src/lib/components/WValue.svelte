<script>
	import { useApp } from '#lib/app.svelte.js';
	import { capName, unit } from '#lib/devices.js';
	import Chart from './Chart.svelte';
	import Spark from './Spark.svelte';
	import { history, stats, withNow } from './history.svelte.js';

	let { d, w, grow = 0 } = $props();
	const app = useApp();
	const { t, f } = app;
	const cap = $derived(d.caps.find((c) => c.id === w.cap) || { id: w.cap });
	const chart = $derived(w.type === 'chart');
	const hours = $derived(chart ? +w.hours || 24 : 24);
	const hist = history(app, () => ({ device: d.id, cap: w.cap, hours }));
	const series = $derived(withNow(hist.points, d, w.cap));
	const range = $derived(stats(series));
	const digits = $derived(Math.abs(range?.max ?? d.state[w.cap] ?? 0) >= 100 ? 0 : 1);
	const u = $derived(unit(t, cap.unit));
</script>

<div class="wd">
	<div class="row" style="justify-content:space-between;align-items:baseline">
		<span class="sm dim">{capName(t, cap)}</span>
		{#if chart}<b class="num" style="font-size:20px;font-weight:400">{f.n(d.state[w.cap], digits)}<small class="dim"> {u}</small></b>{/if}
	</div>
	{#if !chart}<b class="num wbig">{f.n(d.state[w.cap], digits)}<small>{u}</small></b>{/if}
	{#if chart}
		<div class="grow" data-base="150"><Chart points={series} height={150 + grow} {digits} /></div>
	{:else if series.length > 1}
		<div class="grow" data-base="44"><Spark points={series} height={44 + grow} label={capName(t, cap)} /></div>
	{/if}
	{#if range}
		<div class="row sm dim" style="justify-content:space-between">
			<span>{t('w.min')} {f.n(range.min, digits)}</span><span>{t('w.avg')} {f.n(range.avg, digits)}</span><span>{t('w.max')} {f.n(range.max, digits)}</span>
		</div>
	{/if}
</div>
