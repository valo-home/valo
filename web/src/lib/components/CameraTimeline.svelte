<script>
	import { useApp } from '#lib/app.svelte.js';

	let { day, pieces = [], events = [], onplay } = $props();
	const app = useApp();
	const { t, f } = app;
	const start = $derived(new Date(`${day}T00:00:00`).getTime());
	const SPAN = 86400000;
	const pos = (ts) => Math.max(0, Math.min(100, ((new Date(ts).getTime() - start) / SPAN) * 100));
	const blocks = $derived(
		pieces.map((m) => {
			const a = new Date(m.createdAt).getTime();
			return { m, left: pos(a), width: Math.max(0.15, (((m.duration || 600) * 1000) / SPAN) * 100) };
		})
	);
	const marks = $derived(events.map((e) => ({ e, left: pos(e.startedAt) })));
	let hover = $state(null);

	function at(ev) {
		const r = ev.currentTarget.getBoundingClientRect();
		return start + ((ev.clientX - r.left) / r.width) * SPAN;
	}
	function pick(ts) {
		const hit = pieces.find((m) => {
			const a = new Date(m.createdAt).getTime();
			return ts >= a && ts < a + (m.duration || 600) * 1000;
		});
		if (hit) onplay?.(hit, Math.max(0, (ts - new Date(hit.createdAt).getTime()) / 1000));
		else app.toast(t('cam.tl_gap'), 'warn');
	}
	function key(ev) {
		if (ev.key !== 'Enter' || !pieces.length) return;
		onplay?.(pieces.at(-1), 0);
	}
</script>

<div class="tl">
	<div
		class="tl-bar"
		role="slider"
		tabindex="0"
		aria-label={t('cam.timeline')}
		aria-valuemin="0"
		aria-valuemax="24"
		aria-valuenow={hover ? new Date(hover).getHours() : 0}
		onclick={(ev) => pick(at(ev))}
		onkeydown={key}
		onpointermove={(ev) => (hover = at(ev))}
		onpointerleave={() => (hover = null)}
	>
		{#each blocks as b (b.m.id)}<span class="tl-rec" style:left="{b.left}%" style:width="{b.width}%"></span>{/each}
		{#each marks as x (x.e.id)}<span class="tl-ev" class:p={x.e.label !== 'motion'} style:left="{x.left}%" title="{x.e.label} {f.time(x.e.startedAt)}"></span>{/each}
		{#if hover}<span class="tl-h" style:left="{pos(hover)}%"><b>{f.time(hover)}</b></span>{/if}
	</div>
	<div class="tl-ax">{#each [0, 3, 6, 9, 12, 15, 18, 21, 24] as h}<span style:left="{(h / 24) * 100}%">{String(h).padStart(2, '0')}</span>{/each}</div>
	<div class="tl-lg sm dim"><span><i class="rec"></i>{t('cam.tl_recorded')}</span><span><i class="ev"></i>{t('cam.tl_events')}</span></div>
</div>

<style>
	.tl {
		display: grid;
		gap: 4px;
		user-select: none;
	}
	.tl-bar {
		position: relative;
		height: 44px;
		border-radius: 8px;
		background: color-mix(in oklab, var(--ink) 7%, transparent);
		cursor: pointer;
		overflow: hidden;
		touch-action: pan-y;
	}
	.tl-rec {
		position: absolute;
		top: 10px;
		bottom: 10px;
		background: color-mix(in oklab, var(--frost) 55%, transparent);
		border-radius: 3px;
	}
	.tl-ev {
		position: absolute;
		top: 4px;
		bottom: 4px;
		width: 2px;
		margin-left: -1px;
		background: var(--amber);
	}
	.tl-ev.p {
		background: var(--violet);
	}
	.tl-h {
		position: absolute;
		top: 0;
		bottom: 0;
		width: 1px;
		background: var(--ink);
		pointer-events: none;
	}
	.tl-h b {
		position: absolute;
		top: 2px;
		left: 4px;
		font: 500 11px var(--f-m);
		background: var(--panel);
		padding: 0 4px;
		border-radius: 4px;
	}
	.tl-ax {
		position: relative;
		height: 14px;
		font: 11px var(--f-m);
		color: var(--ink-3);
	}
	.tl-ax span {
		position: absolute;
		transform: translateX(-50%);
	}
	.tl-ax span:first-child {
		transform: none;
	}
	.tl-ax span:last-child {
		transform: translateX(-100%);
	}
	.tl-lg {
		display: flex;
		gap: 16px;
		flex-wrap: wrap;
		margin-top: 4px;
	}
	.tl-lg span {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
	.tl-lg i {
		width: 12px;
		height: 8px;
		border-radius: 2px;
	}
	.tl-lg i.rec {
		background: color-mix(in oklab, var(--frost) 55%, transparent);
	}
	.tl-lg i.ev {
		width: 3px;
		background: var(--amber);
	}
</style>
