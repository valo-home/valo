<script>
	import { useApp } from '#lib/app.svelte.js';

	let { values = [], now = -1, marks = [], height = 56, label = '', labels = [], unit = '', digits = 1, series = [], kinds = [], axis = false } = $props();
	const { f } = useApp();
	const W = 600;
	const COLORS = { amber: 'var(--amber)', frost: 'var(--frost)', ok: 'var(--ok)', violet: 'var(--violet)', warn: 'var(--warn)', crit: 'var(--crit)', ink: 'var(--ink-3)' };
	const AUTO = ['amber', 'frost', 'ok', 'violet', 'warn', 'ink'];
	const max = $derived(Math.max(0, ...values.map((v) => v ?? 0)) || 1);
	const min = $derived(Math.min(0, ...values.map((v) => v ?? 0)));
	const zero = $derived((max / (max - min)) * height);
	const bh = (v) => (Math.abs(v) / (max - min)) * height;
	const sorted = $derived([...values].filter((v) => v != null).sort((a, b) => a - b));
	const lo = $derived(sorted[Math.floor(sorted.length / 3)] ?? 0);
	const hi = $derived(sorted[Math.floor((sorted.length * 2) / 3)] ?? 0);
	const bw = $derived(W / Math.max(1, values.length));
	const kind = (i) => Math.min(Math.max(0, Number(kinds[i]) || 0), series.length - 1);
	const color = (k) => COLORS[series[k]?.color] ?? COLORS[AUTO[k % AUTO.length]];
	const fill = (v, i) =>
		series.length ? color(kind(i)) : marks.includes(i) ? 'var(--ok)' : v <= lo ? 'var(--frost)' : v >= hi ? 'var(--amber)' : 'var(--ink-3)';
	const ax = (v) => f.n(v, [0, 1, 2, 3].find((d) => d >= digits || Math.abs(Math.round(v * 10 ** d) / 10 ** d - v) < 1e-9) ?? digits);
	const num = (v) => `${f.n(v, digits)}${unit && v != null ? `\u00a0${unit}` : ''}`;
	const text = (i) => [labels[i], num(values[i]), series.length > 1 ? series[kind(i)]?.label : ''].filter(Boolean).join(', ');
	const ticks = $derived(labels.length ? [0, 0.25, 0.5, 0.75].map((p) => labels[Math.floor(labels.length * p)]).concat(labels.at(-1)) : []);
	const zp = $derived((zero / height) * 100);
	let cur = $state(-1);
	let foc = $state(-1);
	const btns = [];
	const sel = $derived(foc >= 0 ? foc : now >= 0 && now < values.length ? now : values.length - 1);
	function key(e, i) {
		const j = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: values.length - 1 }[e.key];
		if (j == null) return;
		e.preventDefault();
		btns[Math.min(Math.max(j, 0), values.length - 1)]?.focus();
	}
</script>

<div class="bx" class:ax={axis}>
	{#if axis}
		<div class="bx-y mono" aria-hidden="true"><span>{ax(max)}</span>{#if min < 0 && zp > 18 && zp < 82}<span class="bx-z" style="top:{zp.toFixed(1)}%">{ax(0)}</span>{/if}<span>{ax(min)}</span></div>
	{/if}
	<div class="bx-p">
		<svg viewBox="0 0 {W} {height}" style="width:100%;height:auto;display:block" role="img" aria-label={label}>
			{#if cur >= 0}<rect x={(cur * bw).toFixed(1)} y="0" width={bw.toFixed(1)} height={height} fill="var(--line)" />{/if}
			{#each values as v, i}
				{#if v != null}
					<rect x={(i * bw + 0.5).toFixed(1)} y={(v >= 0 ? zero - bh(v) : zero).toFixed(1)} width={Math.max(0.6, bw - 1).toFixed(1)} height={bh(v).toFixed(1)} rx="1" fill={fill(v, i)} opacity={now >= 0 && i < now ? 0.45 : 1} />
				{/if}
			{/each}
			{#if min < 0}<line x1="0" x2={W} y1={zero} y2={zero} stroke="var(--line-2)" stroke-width="1" />{/if}
			{#if now >= 0}<line x1={now * bw} x2={now * bw} y1="0" y2={height} stroke="var(--ink)" stroke-width="1.5" stroke-dasharray="3 3" />{/if}
		</svg>
		<div class="bx-hit">
			{#each values as v, i}<button type="button" bind:this={btns[i]} tabindex={i === sel ? 0 : -1} aria-label={text(i)} onpointerenter={() => (cur = i)} onpointerleave={() => (cur = foc)} onfocus={() => ((foc = i), (cur = i))} onblur={() => ((foc = -1), (cur = -1))} onkeydown={(e) => key(e, i)}></button>{/each}
		</div>
		{#if cur >= 0 && cur < values.length}
			{@const p = ((cur + 0.5) / values.length) * 100}
			<div class="bx-tip" style="left:{p.toFixed(1)}%;transform:translateX(-{p.toFixed(1)}%)" aria-hidden="true">
				{#if labels[cur]}<span class="dim">{labels[cur]}</span>{/if}<b>{num(values[cur])}</b>{#if series.length > 1}<span class="dim">{series[kind(cur)]?.label}</span>{/if}
			</div>
		{/if}
	</div>
	{#if axis && ticks.length}
		<div class="bx-x mono sm dim" aria-hidden="true">{#each ticks as x}<span>{x}</span>{/each}</div>
	{/if}
	{#if axis && series.length > 1}
		<div class="bx-lg sm dim">{#each series as s, k}<span><i style="background:{color(k)}"></i>{s.label}</span>{/each}</div>
	{/if}
</div>

<style>
	.bx {
		display: grid;
		grid-template-columns: minmax(0, 1fr);
		row-gap: 4px;
	}
	.bx.ax {
		grid-template-columns: auto minmax(0, 1fr);
		column-gap: 6px;
	}
	.bx-y {
		position: relative;
		display: flex;
		flex-direction: column;
		justify-content: space-between;
		align-items: flex-end;
		font-size: 10.5px;
		line-height: 1;
		color: var(--ink-3);
	}
	.bx-y .bx-z {
		position: absolute;
		right: 0;
		transform: translateY(-50%);
	}
	.bx-p {
		position: relative;
	}
	.bx-hit {
		position: absolute;
		inset: 0;
		display: flex;
	}
	.bx-hit button {
		flex: 1 1 0;
		min-width: 0;
		padding: 0;
		border: 0;
		border-radius: 2px;
		background: none;
		cursor: default;
	}
	.bx-tip {
		position: absolute;
		bottom: 100%;
		margin-bottom: 6px;
		display: flex;
		gap: 6px;
		align-items: baseline;
		padding: 4px 8px;
		border-radius: 8px;
		border: 1px solid var(--line-2);
		background: var(--raise);
		box-shadow: 0 4px 14px rgb(0 0 0 / 0.2);
		font: 500 11.5px var(--f-m);
		white-space: nowrap;
		pointer-events: none;
		z-index: 5;
	}
	.bx-tip b {
		font-weight: 600;
	}
	.bx-x,
	.bx-lg {
		grid-column: -2 / -1;
		display: flex;
		justify-content: space-between;
	}
	.bx-lg {
		justify-content: flex-start;
		flex-wrap: wrap;
		gap: 4px 14px;
	}
	.bx-lg span {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
	.bx-lg i {
		width: 10px;
		height: 10px;
		border-radius: 3px;
	}
</style>
