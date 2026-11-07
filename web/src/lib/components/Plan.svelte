<script>
	import { useApp } from '#lib/app.svelte.js';
	import { alarm, icon, isOn, lowBat, primary } from '#lib/devices.js';
	import { ICONS } from '#lib/icons.js';
	import { MARK, markers, roomDevices } from '#lib/plan.js';

	let { floor, onroom } = $props();
	const app = useApp();
	const { s, t, f } = app;
	const rooms = $derived(s.rooms.filter((r) => r.floor === floor && r.geom?.w));
	const devs = $derived(Object.values(s.devices));
	const box = $derived.by(() => {
		const g = rooms.map((r) => r.geom);
		return g.length ? [0, 0, Math.max(640, ...g.map((x) => x.x + x.w + 20)), Math.max(400, ...g.map((x) => x.y + x.h + 20))] : [0, 0, 640, 400];
	});

	function info(r) {
		const ds = roomDevices(devs, r.id);
		const lit = ds.filter((d) => d.kind === 'light' && isOn(d));
		const clim = ds.find((d) => d.kind === 'clim' && d.state.t != null) || ds.find((d) => ['trv', 'floor', 'sauna'].includes(d.kind) && d.state.t != null);
		const tgt = ds.find((d) => (d.kind === 'trv' || d.kind === 'floor') && d.state.sp != null);
		const notes = ds
			.map((d) => (!d.available ? ['crit', t('v.offline')] : d.state.leak ? ['crit', t('v.leak')] : d.kind === 'contact' && d.state.open ? ['warn', t('v.open')] : d.kind === 'sauna' && d.state.on ? ['amber', t('v.heating')] : null))
			.filter(Boolean);
		const glow = lit.length ? Math.min(1, 0.4 + Math.max(...lit.map((d) => d.state.bri ?? 100)) / 140) : 0;
		return { ds, clim, tgt, notes, glow, mk: markers(r.geom, ds, r.geom.devs) };
	}
</script>

<svg viewBox={box.join(' ')} role="img" aria-label={t('home.plan', { n: floor })}>
	<defs>
		<radialGradient id="gl"><stop offset="0" stop-color="#ffa64a" stop-opacity=".62" /><stop offset="1" stop-color="#ffa64a" stop-opacity="0" /></radialGradient>
	</defs>
	{#each rooms as r (r.id)}
		{@const g = r.geom}
		{@const x = info(r)}
		<g role="button" tabindex="0" aria-label={r.name} onclick={() => onroom(r)} onkeydown={(e) => e.key === 'Enter' && onroom(r)} style="cursor:pointer">
			<rect class="rr" class:out={r.outdoor} x={g.x} y={g.y} width={g.w} height={g.h} rx="6" />
			{#if x.glow}<circle cx={g.x + g.w / 2} cy={g.y + g.h / 2 + 8} r={Math.min(g.w, g.h) * 0.6} fill="url(#gl)" opacity={x.glow.toFixed(2)} pointer-events="none" />{/if}
			<text class="rn" x={g.x + 12} y={g.y + 22}>{r.name}</text>
			{#if x.clim}<text class="rt" x={g.x + 12} y={g.y + 50}>{f.n(x.clim.state.t, 1)}°</text>{/if}
			{#if x.clim?.state.h != null || x.tgt}
				<text class="rh" x={g.x + 12} y={g.y + 68}>{[x.clim?.state.h != null && `${f.n(x.clim.state.h, 0)}%`, x.tgt && t('home.target', { v: f.n(x.tgt.state.sp, 1) })].filter(Boolean).join(' · ')}</text>
			{/if}
			{#each x.notes as [lvl, txt], i}
				<text class="rx" x={g.x + 12} y={g.y + 88 + i * 15} style="fill:var(--{lvl === 'amber' ? 'amber-ink' : lvl})">{txt}</text>
			{/each}
			{#each x.mk.list as m (m.d.id)}
				{@const d = m.d}
				<g class="mk" class:off={!d.available} class:al={d.available && (alarm(d) || lowBat(d))} class:on={d.available && !alarm(d) && !lowBat(d) && isOn(d)}>
					<title>{d.name}, {primary(app, d)}</title>
					{#if d.kind === 'motion' && d.state.occ}<circle class="pulse" cx={m.x} cy={m.y} r={MARK / 2} />{/if}
					<circle cx={m.x} cy={m.y} r={MARK / 2 - 1} />
					<svg x={m.x - 7} y={m.y - 7} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{@html ICONS[icon(d)] || ICONS.dev}</svg>
				</g>
			{/each}
			{#if x.mk.hidden}<text class="rh" x={g.x + g.w - 10} y={g.y + g.h - 10} text-anchor="end">+{x.mk.hidden}</text>{/if}
		</g>
	{/each}
</svg>
