<script>
	import { useApp } from '#lib/app.svelte.js';
	import Icon from './Icon.svelte';

	let { cam, aim = $bindable(false), onpresets, bar = false } = $props();
	const app = useApp();
	const { t } = app;
	const STEP = 0.25;
	let busy = $state(false);
	let adding = $state(false);
	let name = $state('');
	const enc = $derived(encodeURIComponent(cam.id));

	async function send(body) {
		if (busy) return;
		busy = true;
		try {
			await app.api('POST', `/cameras/${enc}/ptz`, body);
		} catch (e) {
			app.toast(e.message, 'crit');
		} finally {
			busy = false;
		}
	}
	export function point(x, y) {
		return send({ op: 'move', pan: Math.round((x - 0.5) * 100) / 100, tilt: Math.round((0.5 - y) * 100) / 100 });
	}
	async function go(p) {
		busy = true;
		await app.run(() => app.api('POST', `/cameras/${enc}/presets/${encodeURIComponent(p.id)}/go`));
		busy = false;
	}
	async function save() {
		const r = await app.run(() => app.api('POST', `/cameras/${enc}/presets`, { name }), t('cam.saved'));
		if (Array.isArray(r)) {
			onpresets?.(r);
			name = '';
			adding = false;
		}
	}
</script>

{#if !bar}
	<div class="ptz" aria-label={t('cam.ptz')}>
		<button class="ptz-b u" onclick={() => send({ op: 'move', tilt: STEP })} disabled={busy} aria-label={t('cam.ptz_up')}><Icon name="chev" size={18} /></button>
		<button class="ptz-b l" onclick={() => send({ op: 'move', pan: -STEP })} disabled={busy} aria-label={t('cam.ptz_left')}><Icon name="chev" size={18} /></button>
		<button class="ptz-b c" onclick={() => send({ op: 'home' })} disabled={busy} aria-label={t('cam.ptz_home')} title={t('cam.ptz_home')}><Icon name="home" size={16} /></button>
		<button class="ptz-b r" onclick={() => send({ op: 'move', pan: STEP })} disabled={busy} aria-label={t('cam.ptz_right')}><Icon name="chev" size={18} /></button>
		<button class="ptz-b d" onclick={() => send({ op: 'move', tilt: -STEP })} disabled={busy} aria-label={t('cam.ptz_down')}><Icon name="chev" size={18} /></button>
	</div>
{:else}
	<div class="ptz-p">
		<button class="chip" class:amber={aim} aria-pressed={aim} onclick={() => (aim = !aim)} title={t('cam.ptz_aim_hint')}><Icon name="search" size={12} />{t('cam.ptz_aim')}</button>
		{#each cam.presets as p (p.id)}<button class="chip" onclick={() => go(p)} disabled={busy}>{p.name}</button>{/each}
		{#if app.can('admin')}
			{#if adding}
				<span class="row ptz-add"><input class="in" placeholder={t('cam.preset_name')} bind:value={name} /><button class="btn s" onclick={save}>{t('a.save')}</button><button class="ib" onclick={() => (adding = false)} aria-label={t('a.cancel')}><Icon name="x" size={14} /></button></span>
			{:else}
				<button class="chip" onclick={() => (adding = true)} title={t('cam.preset_hint')}><Icon name="plus" size={12} />{t('cam.preset_add')}</button>
			{/if}
		{/if}
	</div>
{/if}

<style>
	.ptz {
		position: absolute;
		right: 12px;
		top: 12px;
		z-index: 3;
		display: grid;
		grid-template-columns: repeat(3, 34px);
		grid-template-rows: repeat(3, 34px);
		gap: 2px;
	}
	.ptz-b {
		display: grid;
		place-items: center;
		border: 0;
		border-radius: 50%;
		background: rgb(0 0 0 / 0.5);
		color: #fff;
		cursor: pointer;
	}
	.ptz-b:disabled {
		opacity: 0.6;
	}
	.ptz-b.u {
		grid-area: 1 / 2;
		transform: rotate(-90deg);
	}
	.ptz-b.l {
		grid-area: 2 / 1;
		transform: rotate(180deg);
	}
	.ptz-b.c {
		grid-area: 2 / 2;
	}
	.ptz-b.r {
		grid-area: 2 / 3;
	}
	.ptz-b.d {
		grid-area: 3 / 2;
		transform: rotate(90deg);
	}
	.ptz-p {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin-top: 10px;
	}
	.ptz-p .chip {
		cursor: pointer;
		height: 28px;
		padding: 0 10px;
	}
	.ptz-add .in {
		width: 160px;
	}
	@media (max-width: 560px) {
		.ptz {
			grid-template-columns: repeat(3, 30px);
			grid-template-rows: repeat(3, 30px);
			right: 8px;
			top: 8px;
		}
	}
</style>
