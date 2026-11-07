<script>
	import { useNodesInitialized, useStore, useSvelteFlow, useViewportInitialized } from '@xyflow/svelte';

	let { key = '', min = 0.8, max = 1, pad = 24 } = $props();
	const flow = useSvelteFlow();
	const store = useStore();
	const ready = useNodesInitialized();
	const live = useViewportInitialized();
	let fitted = '';

	function fit(w, h) {
		const list = flow.getNodes();
		if (!list.length) return false;
		const b = flow.getNodesBounds(list);
		const zoom = Math.min(max, Math.max(min, Math.min((w - pad * 2) / Math.max(1, b.width), (h - pad * 2) / Math.max(1, b.height))));
		const sw = b.width * zoom;
		const sh = b.height * zoom;
		const x = sw + pad * 2 > w ? pad - b.x * zoom : (w - sw) / 2 - b.x * zoom;
		const y = sh + pad * 2 > h ? pad - b.y * zoom : (h - sh) / 2 - b.y * zoom;
		flow.setViewport({ x, y, zoom });
		return true;
	}

	$effect(() => {
		const k = key;
		const w = store.width;
		const h = store.height;
		if (!ready.current || !live.current || !w || !h) return;
		const sig = `${k}|${w}x${h}`;
		if (sig !== fitted && fit(w, h)) fitted = sig;
	});
</script>
