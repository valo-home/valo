<script>
	import { useApp } from '#lib/app.svelte.js';
	import { icon } from '#lib/devices.js';
	import { ICONS } from '#lib/icons.js';
	import { MARK, clamp01, markers, roomDevices, toFraction } from '#lib/plan.js';
	import Icon from './Icon.svelte';

	let { floor, onclose } = $props();
	const app = useApp();
	const { s, t } = app;
	const GRID = 10;
	const MIN_W = 60;
	const MIN_H = 50;
	const snap = (v) => Math.round(v / GRID) * GRID;

	let draft = $state(Object.fromEntries(s.rooms.filter((r) => r.floor === floor && r.geom?.w).map((r) => [r.id, { ...r.geom }])));
	let sel = $state(null);
	let selDev = $state(null);
	let drag = null;
	const devs = $derived(Object.values(s.devices));
	const same = (a, b) => JSON.stringify(a || {}) === JSON.stringify(b || {});
	let svg = $state();
	let busy = $state(false);

	const placed = $derived(s.rooms.filter((r) => r.floor === floor && draft[r.id]));
	const unplaced = $derived(s.rooms.filter((r) => r.floor === floor && !draft[r.id]));
	const changed = $derived(
		s.rooms.filter((r) => {
			const g = draft[r.id];
			if (!g) return false;
			const o = r.geom || {};
			return ['x', 'y', 'w', 'h'].some((k) => g[k] !== o[k]) || !same(g.devs, o.devs);
		})
	);
	const box = $derived.by(() => {
		const g = Object.values(draft);
		return [0, 0, Math.max(640, ...g.map((x) => x.x + x.w + 120)), Math.max(400, ...g.map((x) => x.y + x.h + 120))];
	});

	function point(e) {
		const m = svg.getScreenCTM()?.inverse();
		if (!m) return { x: 0, y: 0 };
		const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(m);
		return { x: p.x, y: p.y };
	}
	function start(e, id, mode, dev = null) {
		e.preventDefault();
		e.stopPropagation();
		sel = id;
		selDev = dev ? { room: id, id: dev } : null;
		const p = point(e);
		drag = { id, mode, dev, p, g: { ...draft[id] } };
		try {
			svg.setPointerCapture(e.pointerId);
		} catch (err) {
			console.warn('pointer capture unavailable', err.message);
		}
	}
	function move(e) {
		if (!drag) return;
		const p = point(e);
		const dx = p.x - drag.p.x;
		const dy = p.y - drag.p.y;
		const g = drag.g;
		if (drag.mode === 'dev') return void setDev(drag.id, drag.dev, toFraction(g, p.x, p.y));
		draft[drag.id] =
			drag.mode === 'move'
				? { ...g, x: Math.max(0, snap(g.x + dx)), y: Math.max(0, snap(g.y + dy)) }
				: { ...g, w: Math.max(MIN_W, snap(g.w + dx)), h: Math.max(MIN_H, snap(g.h + dy)) };
	}
	function end(e) {
		if (drag && svg.hasPointerCapture?.(e.pointerId)) svg.releasePointerCapture(e.pointerId);
		drag = null;
	}
	function setDev(rid, id, pos) {
		const g = draft[rid];
		const next = { ...(g.devs || {}) };
		if (pos) next[id] = pos;
		else delete next[id];
		draft[rid] = { ...g, devs: next };
	}
	function posOf(rid, id) {
		const g = draft[rid];
		const m = markers(g, roomDevices(devs, rid), g.devs).list.find((x) => x.d.id === id);
		return m ? toFraction(g, m.x, m.y) : [0, 1];
	}
	function key(e) {
		if (!sel || !draft[sel]) return;
		const d = { ArrowLeft: [-GRID, 0], ArrowRight: [GRID, 0], ArrowUp: [0, -GRID], ArrowDown: [0, GRID] }[e.key];
		if (!d) return;
		e.preventDefault();
		if (selDev) {
			const [fx, fy] = posOf(selDev.room, selDev.id);
			const g = draft[selDev.room];
			return void setDev(selDev.room, selDev.id, [clamp01(fx + d[0] / Math.max(1, g.w - MARK)), clamp01(fy + d[1] / Math.max(1, g.h - MARK))]);
		}
		const g = draft[sel];
		draft[sel] = e.shiftKey ? { ...g, w: Math.max(MIN_W, g.w + d[0]), h: Math.max(MIN_H, g.h + d[1]) } : { ...g, x: Math.max(0, g.x + d[0]), y: Math.max(0, g.y + d[1]) };
	}
	function place(r) {
		const g = Object.values(draft);
		const y = g.length ? Math.max(...g.map((x) => x.y + x.h)) + GRID * 2 : 20;
		draft[r.id] = { x: 20, y, w: 160, h: 120 };
		sel = r.id;
	}
	function remove(id) {
		delete draft[id];
		draft = { ...draft };
		sel = null;
		selDev = null;
	}
	function clean(rid, g) {
		const here = new Set(roomDevices(devs, rid).map((d) => d.id));
		const kept = Object.fromEntries(Object.entries(g.devs || {}).filter(([id]) => here.has(id)));
		const { devs: _, ...rest } = g;
		return Object.keys(kept).length ? { ...rest, devs: kept } : rest;
	}
	async function save() {
		busy = true;
		const removed = s.rooms.filter((r) => r.floor === floor && r.geom?.w && !draft[r.id]);
		const jobs = [...changed.map((r) => [r.id, clean(r.id, draft[r.id])]), ...removed.map((r) => [r.id, {}])];
		const ok = await app.run(async () => {
			for (const [id, geom] of jobs) await app.api('PATCH', `/rooms/${id}`, { geom });
			return true;
		}, t('rooms.plan_saved'));
		busy = false;
		if (ok) onclose?.();
	}
</script>

<div class="g" style="gap:12px">
	<div class="row" style="flex-wrap:wrap">
		<p class="sm dim" style="margin:0;flex:1;min-width:220px">{t('rooms.plan_hint')}</p>
		<button class="btn" onclick={() => onclose?.()}>{t('a.cancel')}</button>
		<button class="btn pri" disabled={busy || (!changed.length && placed.length === s.rooms.filter((r) => r.floor === floor && r.geom?.w).length)} onclick={save}><Icon name="check" size={16} />{t('a.save')}</button>
	</div>
	{#if unplaced.length}
		<div class="row" style="flex-wrap:wrap;gap:6px">
			<span class="lbl">{t('rooms.unplaced')}</span>
			{#each unplaced as r (r.id)}<button class="btn s" onclick={() => place(r)}><Icon name="plus" size={14} />{r.name}</button>{/each}
		</div>
	{/if}
	<div class="card" style="padding:0;overflow:auto">
		<svg
			bind:this={svg}
			class="pe"
			viewBox={box.join(' ')}
			style="width:100%;min-width:640px;touch-action:none;display:block"
			role="application"
			aria-label={t('rooms.plan_edit')}
			tabindex="0"
			onpointermove={move}
			onpointerup={end}
			onpointercancel={end}
			onkeydown={key}
			onpointerdown={() => ((sel = null), (selDev = null))}
		>
			<defs>
				<pattern id="pe-grid" width={GRID * 2} height={GRID * 2} patternUnits="userSpaceOnUse"><path d="M {GRID * 2} 0 L 0 0 0 {GRID * 2}" fill="none" style="stroke:var(--line)" stroke-width="1" /></pattern>
			</defs>
			<rect x="0" y="0" width={box[2]} height={box[3]} fill="url(#pe-grid)" />
			{#each placed as r (r.id)}
				{@const g = draft[r.id]}
				<g class:on={sel === r.id}>
					<rect class="pe-room" class:out={r.outdoor} x={g.x} y={g.y} width={g.w} height={g.h} rx="6" role="button" tabindex="-1" aria-label={r.name} onpointerdown={(e) => start(e, r.id, 'move')} />
					<text class="rn" x={g.x + 12} y={g.y + 22} pointer-events="none">{r.name}</text>
					<text class="rh" x={g.x + 12} y={g.y + 40} pointer-events="none">{g.w}×{g.h}</text>
					<rect class="pe-handle" x={g.x + g.w - 14} y={g.y + g.h - 14} width="14" height="14" rx="3" role="button" tabindex="-1" aria-label={t('rooms.resize', { name: r.name })} onpointerdown={(e) => start(e, r.id, 'size')} />
					{#each markers(g, roomDevices(devs, r.id), g.devs).list as m (m.d.id)}
						<g class="mk pe-dev" class:auto={m.auto} class:picked={selDev?.id === m.d.id} role="button" tabindex="-1" aria-label={t('rooms.move_dev', { name: m.d.name })} onpointerdown={(e) => start(e, r.id, 'dev', m.d.id)}>
							<title>{m.d.name}</title>
							<circle cx={m.x} cy={m.y} r={MARK / 2 - 1} />
							<svg x={m.x - 7} y={m.y - 7} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" pointer-events="none">{@html ICONS[icon(m.d)] || ICONS.dev}</svg>
						</g>
					{/each}
				</g>
			{/each}
		</svg>
	</div>
	{#if selDev && draft[selDev.room]}
		{@const d = s.devices[selDev.id]}
		<div class="row sm" style="flex-wrap:wrap">
			<b style="font-weight:500">{d?.name}</b>
			<span class="dim">{s.rooms.find((x) => x.id === selDev.room)?.name}</span>
			{#if draft[selDev.room].devs?.[selDev.id]}<button class="btn s ghost" onclick={() => setDev(selDev.room, selDev.id, null)}>{t('rooms.dev_reset')}</button>{/if}
		</div>
	{:else if sel && draft[sel]}
		{@const r = s.rooms.find((x) => x.id === sel)}
		<div class="row sm" style="flex-wrap:wrap">
			<b style="font-weight:500">{r?.name}</b>
			<span class="mono dim">x {draft[sel].x} · y {draft[sel].y} · {draft[sel].w}×{draft[sel].h}</span>
			<button class="btn s ghost" onclick={() => remove(sel)}>{t('rooms.unplace')}</button>
		</div>
	{/if}
</div>

<style>
	.pe-room {
		fill: var(--raise);
		stroke: var(--line-2);
		stroke-width: 1.5;
		cursor: move;
	}
	.pe-room.out {
		stroke-dasharray: 6 4;
	}
	.on .pe-room {
		stroke: var(--amber);
		stroke-width: 2.5;
	}
	.pe-dev {
		cursor: grab;
	}
	.pe-dev.auto circle {
		stroke-dasharray: 3 2;
	}
	.pe-dev.picked circle {
		stroke: var(--amber);
		stroke-width: 2.5;
	}
	.pe-handle {
		fill: var(--amber);
		cursor: nwse-resize;
		opacity: 0.85;
	}
	svg:focus-visible {
		outline: 2px solid var(--frost);
	}
</style>
