<script>
	import { onMount } from 'svelte';
	import { useApp } from '#lib/app.svelte.js';
	import Icon from './Icon.svelte';

	let { camera, sub = false, muted = true, poster = '' } = $props();
	const app = useApp();
	const { t } = app;
	let host = $state();
	let player = null;
	let ready = $state(false);
	let phase = $state('connecting');

	async function define() {
		if (customElements.get('valo-video')) return;
		const { VideoRTC } = await import('#lib/vendor/video-rtc.js');
		class ValoVideo extends VideoRTC {
			constructor() {
				super();
				this.mode = 'mse,mjpeg';
				this.media = 'video,audio';
			}
			oninit() {
				super.oninit();
				this.video.controls = false;
				this.video.muted = true;
				this.video.style.objectFit = 'contain';
			}
		}
		customElements.define('valo-video', ValoVideo);
	}

	let slow = 0;
	function mount(stream) {
		player?.remove();
		phase = 'connecting';
		clearTimeout(slow);
		slow = setTimeout(() => phase === 'connecting' && (phase = 'stalled'), 15000);
		const el = document.createElement('valo-video');
		host.appendChild(el);
		el.video?.addEventListener('playing', () => (phase = 'live'));
		el.video?.addEventListener('waiting', () => phase === 'live' && (phase = 'connecting'));
		el.video?.addEventListener('error', () => {
			phase = 'error';
			console.warn('camera video error', camera, el.video?.error?.code);
		});
		el.src = `/rtc/api/ws?src=${encodeURIComponent(stream)}`;
		player = el;
	}

	onMount(() => {
		let alive = true;
		define()
			.then(() => alive && (ready = true))
			.catch((e) => {
				phase = 'error';
				console.error('camera player failed to load', e?.message);
			});
		return () => {
			alive = false;
			clearTimeout(slow);
			player?.remove();
			player = null;
		};
	});

	$effect(() => {
		if (!ready || !host) return;
		mount(sub ? `${camera}_sub` : camera);
	});

	$effect(() => {
		const v = ready && player?.video;
		if (v) v.muted = muted;
	});
</script>

<div class="cam-live" bind:this={host} style:background-image={poster && phase !== 'live' ? `url(${poster})` : ''}>
	{#if phase !== 'live'}
		<div class="cam-st" role="status">
			{#if phase === 'error'}<Icon name="warn" size={18} />{t('cam.video_error')}{:else if phase === 'stalled'}<Icon name="warn" size={18} />{t('cam.no_video')}{:else}<span class="cam-spin"></span>{t('cam.connecting')}{/if}
		</div>
	{/if}
</div>

<style>
	.cam-live {
		position: relative;
		width: 100%;
		aspect-ratio: 16 / 9;
		background: #000 center / contain no-repeat;
		border-radius: var(--r);
		overflow: hidden;
	}
	.cam-live :global(valo-video) {
		display: block;
		position: absolute;
		inset: 0;
	}
	.cam-st {
		position: absolute;
		left: 50%;
		top: 50%;
		transform: translate(-50%, -50%);
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 6px 12px;
		border-radius: 16px;
		background: rgb(0 0 0 / 0.6);
		color: #fff;
		font-size: 13px;
		z-index: 1;
		pointer-events: none;
	}
	.cam-spin {
		width: 14px;
		height: 14px;
		border: 2px solid rgb(255 255 255 / 0.35);
		border-top-color: #fff;
		border-radius: 50%;
		animation: cam-rot 0.9s linear infinite;
	}
	@keyframes cam-rot {
		to {
			transform: rotate(360deg);
		}
	}
</style>
