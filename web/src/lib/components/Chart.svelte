<script>
	import 'uplot/dist/uPlot.min.css';
	import uPlot from 'uplot';
	import { useApp } from '#lib/app.svelte.js';

	let { points = [], step = false, height = 220, digits = 1, color = '--amber', labels = null } = $props();
	const app = useApp();
	let el = $state();

	$effect(() => {
		if (!el || !points.length) return;
		const css = getComputedStyle(el);
		const c = (v) => css.getPropertyValue(v).trim();
		const cols = points[0].length;
		const raw = points.length === 1 ? [points[0], [Math.max(points[0][0] + 60, Date.now() / 1000), ...points[0].slice(1)]] : points;
		const steps = raw.slice(1).map((p, i) => p[0] - raw[i][0]).sort((x, y) => x - y);
		const gap = Math.max(7200, 6 * (steps[Math.floor(steps.length / 2)] || 0));
		const pts = raw.flatMap((p, i) => (i && p[0] - raw[i - 1][0] > gap ? [[raw[i - 1][0] + 1, ...p.slice(1).map(() => null)], p] : [p]));
		const data = Array.from({ length: cols }, (_, i) => pts.map((p) => (i && typeof p[i] !== 'number' ? null : p[i])));
		const tz = app.s.home?.timezone;
		const axis = { stroke: c('--ink-3'), grid: { stroke: c('--line'), width: 1 }, ticks: { show: false }, font: `11px ${c('--f-m')}` };
		const line = (col, w) => ({ stroke: c(col), width: w, points: { show: false }, paths: step ? uPlot.paths.stepped({ align: 1 }) : undefined });
		const series = [{}, { ...line(color, 2), fill: `color-mix(in srgb, ${c(color)} 14%, transparent)` }];
		if (cols > 3) series.push(line('--line-2', 1), line('--line-2', 1));
		const u = new uPlot(
			{
				width: el.clientWidth,
				height,
				legend: { show: false },
				cursor: { points: { show: false }, drag: { x: false, y: false } },
				tzDate: tz ? (ts) => uPlot.tzDate(new Date(ts * 1e3), tz) : undefined,
				scales: { x: { time: true, range: (_, min, max) => (max - min < 60 ? [min - 1800, max + 1800] : [min, max]) }, ...(labels ? { y: { range: [-0.15, 1.15] } } : {}) },
				axes: [
					{ ...axis, values: (_, v) => v.map((x) => (data[0].at(-1) - data[0][0] > 172800 ? app.f.date(x) : app.f.time(x))) },
					labels
						? { ...axis, size: 72, splits: () => [0, 1], values: (_, v) => v.map((x) => labels[x] ?? '') }
						: { ...axis, size: 52, values: (_, v) => v.map((x) => app.f.n(x, v.every((y) => Number.isInteger(y)) ? 0 : digits)).map((x, i, a) => (i && x === a[i - 1] ? '' : x)) }
				],
				series
			},
			cols > 3 ? [data[0], data[1], data[2], data[3]] : data.slice(0, 2),
			el
		);
		let frame = 0;
		const ro = new ResizeObserver(() => frame || (frame = requestAnimationFrame(() => ((frame = 0), u.setSize({ width: el.clientWidth, height })))));
		ro.observe(el);
		return () => (ro.disconnect(), cancelAnimationFrame(frame), u.destroy());
	});
</script>

<div bind:this={el} style="min-height:{height}px">
	{#if !points.length}<div class="empty" style="height:{height}px;display:grid;place-items:center">{app.t('dev.nodata')}</div>{/if}
</div>
