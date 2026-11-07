<script>
	import { useApp } from '#lib/app.svelte.js';
	import Hint from '#lib/components/Hint.svelte';

	let { store = $bindable(null) } = $props();
	const app = useApp();
	const { t, f } = app;
	let form = $state({ dir: '', minFreeGb: 10, days: 30, maxGb: 0 });
	let busy = $state(false);
	$effect(() => {
		if (!store) return;
		form = { dir: store.dir, minFreeGb: store.minFreeGb, days: store.days, maxGb: store.maxGb };
	});
	const pct = $derived(store?.total ? Math.round((1 - store.free / store.total) * 100) : 0);

	async function save() {
		busy = true;
		const r = await app.run(() => app.api('PATCH', '/media/storage', { dir: form.dir, minFreeGb: +form.minFreeGb, days: +form.days, maxGb: +form.maxGb }), t('cam.storage_saved'));
		busy = false;
		if (r) store = r;
	}
</script>

{#if store}
	<div class="g">
		<div class="cam-disk">
			<div class="row" style="justify-content:space-between"><span class="sm">{store.path}</span><span class="sm dim">{t('cam.free_of', { free: f.bytes(store.free), total: f.bytes(store.total) })}</span></div>
			<div class="bar" role="progressbar" aria-valuenow={pct} aria-valuemin="0" aria-valuemax="100"><i style:width="{pct}%" class:crit={store.low}></i></div>
			<small class="dim">{t('cam.used_by', { size: f.bytes(store.used), n: store.count })}</small>
		</div>
		<label class="f">
			<span>{t('cam.dir')} <Hint k="cam_dir" doc="cameras" /></span>
			<div class="cam-path"><span class="dim sm nobr">{store.root.replace(/\/$/, '')}/</span><input class="in" bind:value={form.dir} disabled={!app.can('admin')} /></div>
			{#if !store.writable}<small style="color:var(--crit)">{t('cam.not_writable')}</small>{/if}
		</label>
		<label class="f">
			<span>{t('cam.min_free')} <Hint k="cam_min_free" doc="cameras" /></span>
			<input class="in" type="number" min="1" step="1" bind:value={form.minFreeGb} disabled={!app.can('admin')} />
		</label>
		<label class="f">
			<span>{t('cam.days')}</span>
			<input class="in" type="number" min="0" step="1" bind:value={form.days} disabled={!app.can('admin')} />
			<small class="dim">{t('cam.days_hint')}</small>
		</label>
		<label class="f">
			<span>{t('cam.max_gb')}</span>
			<input class="in" type="number" min="0" step="1" bind:value={form.maxGb} disabled={!app.can('admin')} />
			<small class="dim">{t('cam.max_gb_hint')}</small>
		</label>
		{#if app.can('admin')}<button class="btn pri" style="justify-self:start" onclick={save} disabled={busy}>{t('a.save')}</button>{/if}
	</div>
{:else}
	<p class="dim">{t('w.loading')}</p>
{/if}

<style>
	.cam-disk {
		display: grid;
		gap: 6px;
	}
	.cam-disk .bar {
		height: 8px;
		border-radius: 4px;
		background: color-mix(in oklab, var(--ink) 10%, transparent);
		overflow: hidden;
	}
	.cam-disk .bar i {
		display: block;
		height: 100%;
		background: var(--ok);
	}
	.cam-disk .bar i.crit {
		background: var(--crit);
	}
	.cam-path {
		display: flex;
		align-items: center;
		gap: 6px;
		min-width: 0;
	}
	.cam-path .in {
		flex: 1;
		min-width: 0;
	}
</style>
