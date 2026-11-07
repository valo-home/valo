<script>
	import { useApp } from '#lib/app.svelte.js';
	import { capName, counterDelta, dayKey, lowBat, primary, readings, unit, value } from '#lib/devices.js';
	import Control from './Control.svelte';
	import Spark from './Spark.svelte';
	import { history, stats, withNow } from './history.svelte.js';

	let { d, grow = 0 } = $props();
	const app = useApp();
	const { s, t, f } = app;
	const st = $derived(d.state);
	const has = (id) => typeof st[id] === 'number';
	const climate = $derived(has('t') && !d.caps.some((c) => (c.id === 'sp' || c.id === 'target') && c.access.includes('w')));
	const power = $derived(!climate && d.caps.some((c) => c.id === 'w'));
	const big = $derived(climate ? ['t', 'h'].filter(has) : power ? ['w'] : []);
	const metric = $derived(climate ? 't' : power ? 'w' : readings(d).find((c) => c.type === 'num')?.id || '');
	const rest = $derived(readings(d).filter((c) => !big.includes(c.id) && c.id !== metric));
	const hist = history(app, () => ({ device: d.id, cap: metric, hours: 24 }));
	const kwh = history(app, () => ({ device: d.id, cap: d.caps.some((c) => c.id === 'kwh') ? 'kwh' : '', hours: 24 }));
	const series = $derived(withNow(hist.points, d, metric));
	const range = $derived(stats(series));
	const today = $derived.by(() => {
		if (!kwh.loaded) return null;
		const tz = s.home?.timezone;
		const key = dayKey(Date.now() / 1000, tz);
		const pts = withNow(kwh.points, d, 'kwh');
		const first = pts.findIndex((p) => dayKey(p[0], tz) === key);
		return first < 0 ? 0 : counterDelta(pts.slice(Math.max(first - 1, 0)), pts[first][0]);
	});
	const unitOf = (id) => unit(t, d.caps.find((c) => c.id === id)?.unit);
	const digits = { t: 1, h: 0, w: 0 };
	const head = $derived(d.kind === 'trv' || d.kind === 'floor' ? `${f.n(st.t, 1)}°` : primary(app, d));
</script>

<div class="wd">
	<div class="row" style="justify-content:space-between;align-items:flex-end;flex-wrap:nowrap">
		{#if big.length}
			<div class="row" style="gap:18px;align-items:baseline">
				{#each big as id (id)}<b class="num wbig">{f.n(st[id], digits[id] ?? 1)}<small>{unitOf(id)}</small></b>{/each}
			</div>
		{:else}
			<b class="num wbig" class:long={head.length > 14}>{head}</b>
		{/if}
		<Control {d} />
	</div>
	{#if power && d.caps.some((c) => c.id === 'on')}<div class="sm dim">{st.on ? t('v.on') : t('v.off')}</div>{/if}
	{#if rest.length || today != null}
		<dl class="wkv">
			{#if today != null}<div><dt>{t('w.today')}</dt><dd class="num">{f.n(today, 2)} {unit(t, 'kWh')}</dd></div>{/if}
			{#each rest.slice(0, 6) as c (c.id)}<div><dt>{c.id === 'kwh' ? t('w.total') : capName(t, c)}</dt><dd class="num">{value(app, d, c.id)}</dd></div>{/each}
		</dl>
	{/if}
	{#if metric && series.length > 1}
		<div>
			<div class="grow" data-base="44"><Spark points={series} height={44 + grow} label={capName(t, d.caps.find((c) => c.id === metric) || { id: metric })} /></div>
			{#if range}<div class="row sm dim" style="justify-content:space-between"><span>{t('w.min')} {f.n(range.min, digits[metric] ?? 1)}</span><span>{t('dev.h24')}</span><span>{t('w.max')} {f.n(range.max, digits[metric] ?? 1)}</span></div>{/if}
		</div>
	{/if}
	<div class="row sm dim" style="gap:8px">
		{#if !d.available}<span class="chip crit">{t('v.offline')}</span>{/if}
		{#if typeof st.bat === 'number'}<span class="chip {lowBat(d) ? 'crit' : ''}">{t('cap.bat')} {st.bat}%</span>{/if}
		{#if d.lastSeen}<span>{t('w.updated', { ago: f.ago(d.lastSeen) })}</span>{/if}
	</div>
</div>
