<script>
	import { forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY } from 'd3-force';
	import { useApp } from '#lib/app.svelte.js';

	let { data, onpick, picked = null } = $props();
	const app = useApp();
	const { s } = app;
	const W = 900;
	const H = 620;
	const graph = $derived.by(() => {
		const nodes = (data?.nodes || []).map((n) => ({ id: n.ieeeAddr, type: n.type, name: s.devices[n.ieeeAddr]?.name || n.friendlyName, failed: n.failed?.length > 0 }));
		const ids = new Set(nodes.map((n) => n.id));
		const links = (data?.links || [])
			.filter((l) => ids.has(l.source?.ieeeAddr ?? l.sourceIeeeAddr) && ids.has(l.target?.ieeeAddr ?? l.targetIeeeAddr))
			.map((l) => ({ source: l.source?.ieeeAddr ?? l.sourceIeeeAddr, target: l.target?.ieeeAddr ?? l.targetIeeeAddr, lqi: l.lqi ?? l.linkquality ?? 0 }));
		const coord = nodes.find((n) => n.type === 'Coordinator');
		if (coord) Object.assign(coord, { fx: W / 2, fy: H / 2 });
		const sim = forceSimulation(nodes)
			.force('link', forceLink(links).id((d) => d.id).distance((l) => 50 + (255 - Math.min(255, l.lqi)) * 0.45).strength(0.7))
			.force('charge', forceManyBody().strength(-260))
			.force('collide', forceCollide(26))
			.force('x', forceX(W / 2).strength(0.04))
			.force('y', forceY(H / 2).strength(0.06))
			.stop();
		for (let i = 0; i < 320; i++) sim.tick();
		for (const n of nodes) ((n.x = Math.max(30, Math.min(W - 30, n.x))), (n.y = Math.max(24, Math.min(H - 24, n.y))));
		return { nodes, links };
	});
	const col = (q) => (q >= 120 ? 'var(--ok)' : q >= 60 ? 'var(--warn)' : 'var(--crit)');
	const r = (n) => (n.type === 'Coordinator' ? 14 : n.type === 'Router' ? 9 : 6);
</script>

<svg viewBox="0 0 {W} {H}" style="width:100%;height:auto;display:block" role="img" aria-label="Zigbee">
	{#each graph.links as l, i (i)}
		<line x1={l.source.x} y1={l.source.y} x2={l.target.x} y2={l.target.y} stroke={col(l.lqi)} stroke-width={1 + l.lqi / 90} opacity={picked && picked !== l.source.id && picked !== l.target.id ? 0.15 : 0.7} />
	{/each}
	{#each graph.nodes as n (n.id)}
		<g role="button" tabindex="0" style="cursor:pointer" onclick={() => onpick?.(n.id)} onkeydown={(e) => e.key === 'Enter' && onpick?.(n.id)}>
			<circle cx={n.x} cy={n.y} r={r(n)} fill={n.failed ? 'transparent' : n.type === 'Coordinator' ? 'var(--amber)' : n.type === 'Router' ? 'var(--frost)' : 'var(--ink-3)'} stroke={n.failed ? 'var(--crit)' : picked === n.id ? 'var(--ink)' : 'var(--panel)'} stroke-width="2" stroke-dasharray={n.failed ? '3 3' : null} />
			<text x={n.x} y={n.y + r(n) + 12} text-anchor="middle" style="font:500 10.5px var(--f-d);fill:var(--ink-2)">{n.name}</text>
		</g>
	{/each}
</svg>
