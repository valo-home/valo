<script>
	import { onMount } from 'svelte';
	import { useApp } from '#lib/app.svelte.js';
	import Hint from './Hint.svelte';
	import Icon from './Icon.svelte';
	import Toggle from './Toggle.svelte';

	let { camera, admin = false, onsaved } = $props();
	const app = useApp();
	const { t } = app;
	const LABELS = ['person', 'car', 'animal', 'bicycle', 'motorcycle', 'truck', 'bus'];
	const MAX_ZONES = 8;
	const MAX_POINTS = 16;
	const label = (l) => (t.has(`cam.l_${l}`) ? t(`cam.l_${l}`) : l);
	const copy = (x) => JSON.parse(JSON.stringify(x ?? null));

	let det = $state({ enabled: false, labels: [], score: 0.55 });
	let zones = $state([]);
	let sel = $state(-1);
	let point = $state(-1);
	let drag = $state(null);
	let busy = $state(false);
	let ext = $state(null);
	let frame = $state();
	let stamp = $state(Date.now());
	let broken = $state(false);
	let ratio = $state(16 / 9);
	let loaded = '';

	$effect(() => {
		const key = `${camera?.id}:${JSON.stringify(camera?.record?.detect)}:${JSON.stringify(camera?.record?.zones)}`;
		if (!camera || key === loaded) return;
		loaded = key;
		const d = camera.record?.detect || {};
		det = { enabled: !!d.enabled, labels: [...(d.labels || ['person', 'car', 'animal'])], score: d.score ?? 0.55 };
		zones = copy(camera.record?.zones || []);
		sel = zones.length ? 0 : -1;
		point = -1;
	});

	const src = $derived(camera ? `/api/v1/cameras/${encodeURIComponent(camera.id)}/preview?full=1&t=${stamp}` : '');
	const zone = $derived(sel >= 0 ? zones[sel] : null);
	const short = $derived(zones.find((z) => z.points.length < 3));
	const norm = (d, z) => JSON.stringify({ enabled: !!d?.enabled, labels: [...(d?.labels || ['person', 'car', 'animal'])].sort(), score: d?.score ?? 0.55, zones: z || [] });
	const motionClips = $derived(!!camera && camera.record?.mode !== 'off' && (!camera.record?.labels?.length || camera.record.labels.includes('motion')));
	const dirty = $derived(!!camera && norm(det, zones) !== norm(camera.record?.detect, camera.record?.zones));

	onMount(async () => {
		try {
			ext = await app.api('GET', '/extensions/fi.valo.vision');
		} catch (e) {
			console.info('vision extension not installed', e?.message);
			ext = { status: 'missing', enabled: false };
		}
	});
	const ready = $derived(!ext || (ext.enabled && ext.status === 'running'));

	function toggleLabel(l) {
		det.labels = det.labels.includes(l) ? det.labels.filter((x) => x !== l) : [...det.labels, l];
	}

	function addZone() {
		if (zones.length >= MAX_ZONES) return;
		let n = zones.length + 1;
		while (zones.some((z) => z.id === `z${n}`)) n++;
		zones = [...zones, { id: `z${n}`, name: t('cam.vis_zone_n', { n }), kind: 'include', points: [] }];
		sel = zones.length - 1;
		point = -1;
	}

	function removeZone() {
		if (sel < 0) return;
		zones = zones.filter((_, i) => i !== sel);
		sel = zones.length ? Math.min(sel, zones.length - 1) : -1;
		point = -1;
	}

	function removePoint(i = point) {
		if (!zone || !zone.points.length) return;
		const at = i >= 0 ? i : zone.points.length - 1;
		zone.points = zone.points.filter((_, k) => k !== at);
		point = -1;
	}

	function pos(e) {
		const r = frame.getBoundingClientRect();
		const x = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
		const y = Math.min(1, Math.max(0, (e.clientY - r.top) / r.height));
		return [Math.round(x * 10000) / 10000, Math.round(y * 10000) / 10000];
	}

	function place(e) {
		if (!admin || drag || e.button > 0) return;
		if (!zone) {
			if (zones.length >= MAX_ZONES) return;
			addZone();
		}
		if (zone.points.length >= MAX_POINTS) {
			app.toast(t('cam.vis_limit', { zones: MAX_ZONES, points: MAX_POINTS }), 'warn');
			return;
		}
		zone.points = [...zone.points, pos(e)];
		point = zone.points.length - 1;
	}

	function grab(e, zi, pi) {
		if (!admin) return;
		e.stopPropagation();
		e.preventDefault();
		sel = zi;
		point = pi;
		drag = { zi, pi, moved: false };
		e.currentTarget.setPointerCapture?.(e.pointerId);
	}

	function move(e) {
		if (!drag) return;
		zones[drag.zi].points[drag.pi] = pos(e);
		drag.moved = true;
	}

	function drop() {
		drag = null;
	}

	function key(e) {
		if (!admin || point < 0 || !zone) return;
		const step = e.shiftKey ? 0.05 : 0.01;
		const d = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[e.key];
		if (d) {
			e.preventDefault();
			const [x, y] = zone.points[point];
			zone.points[point] = [Math.min(1, Math.max(0, x + d[0])), Math.min(1, Math.max(0, y + d[1]))].map((v) => Math.round(v * 10000) / 10000);
		} else if (e.key === 'Delete' || e.key === 'Backspace') {
			e.preventDefault();
			removePoint();
		}
	}

	async function save() {
		if (short) {
			app.toast(t('cam.vis_need3', { name: short.name || short.id }), 'warn');
			return;
		}
		busy = true;
		const r = await app.run(
			() =>
				app.api('PATCH', `/cameras/${encodeURIComponent(camera.id)}`, {
					record: { detect: { enabled: det.enabled, labels: det.labels, score: Math.round(det.score * 100) / 100 }, zones: zones.map((z) => ({ id: z.id, name: z.name, kind: z.kind, points: z.points })) }
				}),
			t('cam.vis_saved')
		);
		busy = false;
		if (r && typeof r === 'object') {
			loaded = '';
			onsaved?.(r);
		}
	}

	function reset() {
		const d = camera.record?.detect || {};
		det = { enabled: !!d.enabled, labels: [...(d.labels || ['person', 'car', 'animal'])], score: d.score ?? 0.55 };
		zones = copy(camera.record?.zones || []);
		sel = zones.length ? 0 : -1;
		point = -1;
	}
</script>

{#if camera}
	<div class="g cvz">
		<div class="cvz-head">
			<Toggle on={det.enabled} label={t('cam.vis_enabled')} disabled={!admin} onclick={() => (det.enabled = !det.enabled)} />
			<span>{t('cam.vis_enabled')} <Hint k="cam_vision" doc="cameras" /></span>
		</div>
		{#if !ready}<p class="sm cvz-warn">{t('cam.vis_no_ext')}</p>{/if}
		{#if motionClips}<p class="sm dim">{t('cam.vis_motion_note', { section: t('cam.recording'), list: t('cam.rec_labels'), mark: t('cam.l_motion') })}</p>{/if}

		<div class="f">
			<span>{t('cam.vis_labels')}</span>
			<div class="cvz-labels">
				{#each LABELS as l (l)}
					<button type="button" class="chip" class:amber={det.labels.includes(l)} aria-pressed={det.labels.includes(l)} disabled={!admin} onclick={() => toggleLabel(l)}>{label(l)}</button>
				{/each}
			</div>
		</div>

		<label class="f">
			<span>{t('cam.vis_score')} <b class="mono">{Math.round(det.score * 100)}%</b></span>
			<input type="range" min="0.2" max="0.95" step="0.05" bind:value={det.score} disabled={!admin} />
			<small class="dim">{t('cam.vis_score_hint')}</small>
		</label>

		<div class="f">
			<div class="row cvz-bar">
				<span>{t('cam.vis_zones')}</span>
				<span class="sp"></span>
				<button type="button" class="btn cvz-b" onclick={() => ((stamp = Date.now()), (broken = false))} title={t('cam.vis_refresh')} aria-label={t('cam.vis_refresh')}><Icon name="refresh" size={14} /></button>
				{#if admin}<button type="button" class="btn cvz-b" onclick={addZone} disabled={zones.length >= MAX_ZONES}><Icon name="plus" size={14} /> {t('cam.vis_add')}</button>{/if}
			</div>
			{#if zones.length}
				<div class="cvz-labels" role="listbox" aria-label={t('cam.vis_zones')}>
					{#each zones as z, i (z.id)}
						<button type="button" role="option" aria-selected={sel === i} class="chip" class:ok={z.kind === 'include'} class:crit={z.kind === 'exclude'} class:cvz-on={sel === i} onclick={() => ((sel = i), (point = -1))}>{z.name || z.id} <small class="dim">{t('cam.vis_points', { n: z.points.length })}</small></button>
					{/each}
				</div>
			{:else}
				<small class="dim">{t('cam.vis_none')}</small>
			{/if}

			<div
				class="cvz-frame"
				class:edit={admin}
				style:aspect-ratio={ratio}
				bind:this={frame}
				role="button"
				aria-label={t('cam.vis_frame')}
				tabindex="0"
				onpointerdown={place}
				onpointermove={move}
				onpointerup={drop}
				onpointercancel={drop}
				onkeydown={key}
			>
				{#if !broken}
					<img
						{src}
						alt=""
						draggable="false"
						onload={(e) => e.currentTarget.naturalWidth && (ratio = e.currentTarget.naturalWidth / e.currentTarget.naturalHeight)}
						onerror={() => (broken = true)}
					/>
				{:else}
					<span class="cvz-empty sm dim">{t('cam.vis_no_frame')}</span>
				{/if}
				<svg viewBox="0 0 1 1" preserveAspectRatio="none" aria-hidden="true">
					{#each zones as z, i (z.id)}
						{#if z.points.length}
							<polygon
								points={z.points.map((p) => p.join(',')).join(' ')}
								class={z.kind}
								class:on={sel === i}
							/>
						{/if}
					{/each}
				</svg>
				{#if zone}
					{#each zone.points as p, pi (pi)}
						<button
							type="button"
							class="cvz-pt {zone.kind}"
							class:on={point === pi}
							style:left="{p[0] * 100}%"
							style:top="{p[1] * 100}%"
							aria-label="{zone.name} {pi + 1}"
							onpointerdown={(e) => grab(e, sel, pi)}
							ondblclick={(e) => (e.stopPropagation(), removePoint(pi))}
							onclick={(e) => e.stopPropagation()}
						></button>
					{/each}
				{/if}
			</div>
			{#if admin}<small class="dim">{t('cam.vis_help')}</small>{/if}
		</div>

		{#if zone && admin}
			<div class="cvz-zone">
				<label class="f">
					<span>{t('cam.vis_name')}</span>
					<input class="in" maxlength="40" bind:value={zone.name} />
				</label>
				<div class="seg">
					<button type="button" class:on={zone.kind === 'include'} onclick={() => (zone.kind = 'include')}>{t('cam.vis_include')}</button>
					<button type="button" class:on={zone.kind === 'exclude'} onclick={() => (zone.kind = 'exclude')}>{t('cam.vis_exclude')}</button>
				</div>
			</div>
			<div class="row cvz-tools">
				<button type="button" class="btn cvz-b" onclick={() => removePoint()} disabled={!zone.points.length}>{t('cam.vis_del_point')}</button>
				<button type="button" class="btn cvz-b" onclick={removeZone}><Icon name="trash" size={14} /> {t('cam.vis_del_zone')}</button>
			</div>
		{/if}

		{#if admin}
			<div class="row cvz-tools">
				<button class="btn pri" onclick={save} disabled={busy || !dirty}>{t('a.save')}</button>
				{#if dirty}<button class="btn" onclick={reset} disabled={busy}>{t('a.cancel')}</button>{/if}
			</div>
		{/if}
	</div>
{/if}

<style>
	.cvz-head {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr);
		align-items: center;
		gap: 12px;
	}
	.cvz-warn {
		color: var(--warn);
		margin: 0;
	}
	.cvz-labels {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.cvz-labels .chip {
		height: 28px;
		padding: 0 10px;
		cursor: pointer;
	}
	.cvz-labels .chip:disabled {
		cursor: default;
	}
	.cvz-labels .chip.cvz-on {
		box-shadow: inset 0 0 0 1px currentColor;
		background: color-mix(in srgb, currentColor 10%, transparent);
	}
	.cvz-bar {
		gap: 6px;
		flex-wrap: wrap;
	}
	.cvz-b {
		height: 30px;
		padding: 0 10px;
		font-size: 12.5px;
	}
	.cvz-bar .sp {
		flex: 1;
	}
	.cvz-zone {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-end;
		gap: 12px;
	}
	.cvz-zone .f {
		flex: 1 1 220px;
	}
	.cvz-tools {
		gap: 8px;
		flex-wrap: wrap;
	}
	.cvz-frame {
		position: relative;
		width: 100%;
		border-radius: var(--r);
		overflow: hidden;
		background: color-mix(in oklab, var(--ink) 8%, var(--sunk));
		border: 1px solid var(--line);
		touch-action: none;
		user-select: none;
		-webkit-user-select: none;
		outline: none;
	}
	.cvz-frame:focus-visible {
		box-shadow: 0 0 0 2px var(--amber);
	}
	.cvz-frame.edit {
		cursor: crosshair;
	}
	.cvz-frame img {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		object-fit: fill;
		pointer-events: none;
	}
	.cvz-empty {
		position: absolute;
		inset: 0;
		display: grid;
		place-items: center;
		padding: 16px;
		text-align: center;
	}
	.cvz-frame svg {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
	}
	.cvz-frame polygon {
		pointer-events: none;
		vector-effect: non-scaling-stroke;
		stroke-width: 2;
		stroke-linejoin: round;
		fill-opacity: 0.16;
	}
	.cvz-frame polygon.include {
		stroke: var(--ok);
		fill: var(--ok);
	}
	.cvz-frame polygon.exclude {
		stroke: var(--crit);
		fill: var(--crit);
		stroke-dasharray: 6 4;
	}
	.cvz-frame polygon.on {
		stroke-width: 3;
		fill-opacity: 0.28;
	}
	.cvz-pt {
		position: absolute;
		width: 28px;
		height: 28px;
		margin: -14px 0 0 -14px;
		border: 0;
		padding: 0;
		background: none;
		touch-action: none;
		cursor: grab;
	}
	.cvz-pt::after {
		content: '';
		position: absolute;
		inset: 8px;
		border-radius: 50%;
		background: var(--raise);
		border: 2px solid var(--ok);
		box-shadow: 0 1px 4px rgb(0 0 0 / 0.4);
	}
	.cvz-pt.exclude::after {
		border-color: var(--crit);
	}
	.cvz-pt.on::after {
		inset: 6px;
		background: var(--amber);
	}
</style>
