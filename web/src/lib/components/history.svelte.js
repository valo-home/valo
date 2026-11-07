import { onMount } from 'svelte';

/** Точки истории возможности устройства. Новые значения приходят событиями state, полная перезагрузка раз в 15 минут как страховка */
export function history(app, get) {
	const st = $state({ points: [], loaded: false });
	let key = '';
	async function load() {
		const { device, cap, hours } = get();
		if (!device || !cap) return;
		const k = `${device}|${cap}|${hours}`;
		const r = await app.api('GET', `/devices/${encodeURIComponent(device)}/history?cap=${encodeURIComponent(cap)}&hours=${hours}`).catch((e) => {
			console.warn('widget history failed', device, cap, e?.message);
			return null;
		});
		if (k !== key && key) return;
		st.points = r?.points || [];
		st.loaded = true;
	}
	$effect(() => {
		const { device, cap, hours } = get();
		const k = `${device}|${cap}|${hours}`;
		if (k !== key) {
			st.points = [];
			st.loaded = false;
		}
		key = k;
		load();
	});
	onMount(() => {
		const off = app.on('state', (d) => {
			const { device, cap, hours } = get();
			const v = d?.s?.[cap];
			if (d?.id !== device || typeof v !== 'number' || !st.loaded || hours > 48) return;
			const ts = Date.now() / 1000;
			const edge = ts - hours * 3600;
			const last = st.points.at(-1);
			const pts = last && ts - last[0] < 20 ? [...st.points.slice(0, -1), [ts, v]] : [...st.points, [ts, v]];
			st.points = pts.filter((p) => p[0] >= edge);
		});
		const i = setInterval(load, 900000);
		return () => (off(), clearInterval(i));
	});
	return st;
}

export function withNow(points, d, cap) {
	const v = d?.state?.[cap];
	return typeof v === 'number' ? [...points, [Date.now() / 1000, v]] : points;
}

export function stats(points) {
	const vs = points.map((p) => p[1]).filter((v) => typeof v === 'number');
	if (!vs.length) return null;
	return { min: Math.min(...vs), max: Math.max(...vs), avg: vs.reduce((a, b) => a + b, 0) / vs.length };
}
