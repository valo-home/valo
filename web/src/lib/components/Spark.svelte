<script>
	let { points = [], height = 44, color = 'var(--amber)', label = '' } = $props();
	const W = 300;
	const nums = $derived(points.filter((p) => typeof p[1] === 'number'));
	const path = $derived.by(() => {
		if (nums.length < 2) return null;
		const t0 = nums[0][0];
		const t1 = nums.at(-1)[0];
		const vs = nums.map((p) => p[1]);
		const lo = Math.min(...vs);
		const hi = Math.max(...vs);
		const span = hi - lo || 1;
		const x = (t) => ((t - t0) / (t1 - t0 || 1)) * W;
		const y = (v) => height - 3 - ((v - lo) / span) * (height - 6);
		const line = nums.map((p, i) => `${i ? 'L' : 'M'}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join('');
		return { line, area: `${line}L${W},${height}L0,${height}Z` };
	});
</script>

{#if path}
	<svg viewBox="0 0 {W} {height}" preserveAspectRatio="none" style="width:100%;height:{height}px;display:block" role="img" aria-label={label}>
		<path d={path.area} fill={color} opacity="0.12" />
		<path d={path.line} fill="none" stroke={color} stroke-width="1.6" vector-effect="non-scaling-stroke" />
	</svg>
{/if}
