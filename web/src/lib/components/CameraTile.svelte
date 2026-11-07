<script>
	import { onMount } from 'svelte';
	import { useApp } from '#lib/app.svelte.js';
	import Icon from './Icon.svelte';

	let { cam, every = 10, compact = false } = $props();
	const app = useApp();
	const { s, t, f } = app;
	const d = $derived(s.devices[cam.deviceId]);
	const room = $derived(s.rooms.find((r) => r.id === (d?.roomId ?? cam.roomId))?.name || '');
	const code = $derived(cam.status?.code || 'ok');
	const online = $derived((d ? d.available : cam.available) && !['offline', 'other_device', 'auth_api', 'auth_stream', 'driver_stopped'].includes(code));
	const moving = $derived(!!(d?.state?.occ ?? cam.state?.occ));
	let el = $state();
	let src = $state('');
	let failed = $state(false);
	let at = $state(0);
	let seen = false;

	function load() {
		if (!seen || document.hidden) return;
		const url = `/api/v1/cameras/${encodeURIComponent(cam.id)}/preview?t=${Date.now()}`;
		const img = new Image();
		img.onload = () => {
			src = url;
			failed = false;
			at = Date.now();
		};
		img.onerror = () => {
			failed = true;
			console.warn('camera preview failed', cam.id);
		};
		img.src = url;
	}

	onMount(() => {
		const io = new IntersectionObserver((es) => {
			const was = seen;
			seen = es.some((e) => e.isIntersecting);
			if (seen && !was) load();
		});
		io.observe(el);
		const i = setInterval(load, every * 1000);
		const vis = () => !document.hidden && load();
		document.addEventListener('visibilitychange', vis);
		return () => (io.disconnect(), clearInterval(i), document.removeEventListener('visibilitychange', vis));
	});
</script>

<a class="cam-tile" class:cmp={compact} href={app.path(`/cameras/${encodeURIComponent(cam.id)}`)} bind:this={el} aria-label={d?.name ?? cam.name}>
	<div class="cam-pic">
		{#if src}<img {src} alt="" />{/if}
		{#if !src || failed || !online}
			<div class="cam-ph"><Icon name="camera" size={compact ? 22 : 30} /><span>{!online && code !== 'ok' ? t(`cam.st_${code}`) : !online ? t('v.offline') : code === 'no_video' ? t('cam.st_no_video') : failed ? t('cam.no_picture') : t('cam.connecting')}</span></div>
		{/if}
		<div class="cam-badges">
			{#if moving}<span class="chip amber cam-b"><Icon name="motion" size={12} />{t('v.motion')}</span>{/if}
			{#if !online}<span class="chip crit cam-b">{t('v.offline')}</span>{:else if code === 'no_video'}<span class="chip warn cam-b">{t('cam.st_no_video')}</span>{/if}
			{#if cam.record?.mode === 'continuous'}<span class="chip cam-b"><Icon name="record" size={12} />{t('cam.rec_on')}</span>{/if}
		</div>
	</div>
	<div class="cam-cap">
		<span class="cam-n">{d?.name ?? cam.name}</span>
		<small class="dim">{room}{#if room && at}{' · '}{/if}{#if at}{f.sec(at)}{/if}</small>
	</div>
</a>

<style>
	.cam-tile {
		display: grid;
		gap: 10px;
		color: inherit;
		text-decoration: none;
		background: var(--panel);
		border: 1px solid var(--line);
		border-radius: var(--r);
		padding: 10px;
		min-width: 0;
	}
	.cam-tile:hover {
		border-color: var(--line-2);
	}
	.cam-tile.cmp {
		padding: 0;
		border: 0;
		background: none;
	}
	.cam-pic {
		position: relative;
		aspect-ratio: 16 / 9;
		border-radius: calc(var(--r) - 4px);
		overflow: hidden;
		background: color-mix(in oklab, var(--ink) 8%, transparent);
	}
	.cam-pic img {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: block;
	}
	.cam-ph {
		position: absolute;
		inset: 0;
		display: grid;
		place-content: center;
		justify-items: center;
		gap: 6px;
		color: var(--ink-2);
		font-size: 12px;
		background: color-mix(in oklab, var(--panel) 70%, transparent);
	}
	.cam-badges {
		position: absolute;
		left: 8px;
		top: 8px;
		display: flex;
		gap: 6px;
		flex-wrap: wrap;
	}
	.cam-b {
		background: var(--panel);
	}
	.cam-cap {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 8px;
		min-width: 0;
		padding: 0 2px;
	}
	.cam-n {
		font-weight: 600;
		overflow-wrap: anywhere;
	}
	.cam-cap small {
		white-space: nowrap;
	}
</style>
