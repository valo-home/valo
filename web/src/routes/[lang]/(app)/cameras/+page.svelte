<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { useApp } from '#lib/app.svelte.js';
	import CameraTile from '#lib/components/CameraTile.svelte';
	import DriverFields from '#lib/components/DriverFields.svelte';
	import Hint from '#lib/components/Hint.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import Modal from '#lib/components/Modal.svelte';
	import Storage from './Storage.svelte';

	const app = useApp();
	const { s, t, f } = app;
	const tx = (x) => (x && typeof x === 'object' ? (x[app.lang] ?? x.en ?? Object.values(x)[0]) : (x ?? ''));
	let cams = $state(null);
	let drivers = $state([]);
	let store = $state(null);
	let addModal = $state();
	let storeModal = $state();
	let busy = $state(false);
	let form = $state({ driver: '', name: '', roomId: '', config: {} });
	const drv = $derived(drivers.find((d) => d.id === form.driver));
	const live = $derived((cams || []).filter((c) => s.devices[c.deviceId]));

	async function load() {
		const [c, d, st] = await Promise.all([
			app.api('GET', '/cameras'),
			app.api('GET', '/cameras/drivers'),
			app.api('GET', '/media/storage').catch((e) => (console.warn('storage info failed', e?.message), null))
		]);
		cams = c;
		drivers = d;
		store = st;
	}
	const reload = () => load().catch((e) => console.warn('cameras reload failed', e?.message));
	onMount(() => {
		load().catch((e) => app.toast(e.message, 'crit'));
		const off = [
			app.on('device', (d) => d?.kind === 'camera' && !cams?.some((c) => c.deviceId === d.id) && reload()),
			app.on('device_gone', (d) => cams?.some((c) => c.deviceId === d?.id) && reload())
		];
		return () => off.forEach((x) => x());
	});

	function openAdd() {
		const first = drivers.find((d) => d.status === 'running') || drivers[0];
		form = { driver: first?.id || '', name: '', roomId: '', config: {} };
		pick();
		addModal.show();
	}
	function pick() {
		const d = drivers.find((x) => x.id === form.driver);
		form.config = Object.fromEntries((d?.fields || []).map((fd) => [fd.key, fd.type === 'secret' ? '' : (fd.default ?? '')]));
	}
	async function add() {
		busy = true;
		const r = await app.run(() => app.api('POST', '/cameras', { driver: form.driver, name: form.name, roomId: form.roomId || null, config: $state.snapshot(form.config) }), t('cam.added', { name: form.name }));
		busy = false;
		if (r?.id) {
			addModal.hide();
			goto(app.path(`/cameras/${encodeURIComponent(r.id)}`));
		}
	}
</script>

<svelte:head><title>{t('nav.cameras')} · valo</title></svelte:head>

<div class="ph">
	<div>
		<h1>{t('nav.cameras')} <Hint k="p_cameras" doc="cameras" /></h1>
		<p>
			{t('cam.sub', { n: live.length })}{#if store}{' · '}{t('cam.store_line', { free: f.bytes(store.free), used: f.bytes(store.used) })}{/if}
		</p>
	</div>
	{#if app.can('admin')}
		<div class="row">
			<button class="btn" onclick={() => storeModal.show()}><Icon name="folder" size={16} />{t('cam.storage')}</button>
			<button class="btn pri" onclick={openAdd} disabled={!drivers.length}><Icon name="plus" size={16} />{t('cam.add')}</button>
		</div>
	{/if}
</div>

{#if store?.low}
	<div class="card cam-warn" role="alert"><Icon name="warn" size={18} /><span>{t('cam.low_space', { free: f.bytes(store.free), min: f.n(store.minFreeGb, 0) })}</span></div>
{/if}

{#if cams === null}
	<p class="dim">{t('w.loading')}</p>
{:else if !live.length}
	<div class="empty cam-empty">
		<Icon name="camera" size={28} />
		<p>{t('cam.none')}</p>
		{#if !drivers.length}
			<p class="sm">{t('cam.no_drivers')}</p>
			{#if app.can('admin')}<a class="btn s" href={app.path('/extensions')}>{t('cam.open_catalog')}</a>{/if}
		{:else if app.can('admin')}
			<button class="btn s pri" onclick={openAdd}><Icon name="plus" size={14} />{t('cam.add')}</button>
		{/if}
	</div>
{:else}
	<div class="cam-grid">
		{#each live as c (c.id)}<CameraTile cam={c} />{/each}
	</div>
{/if}

<Modal bind:this={addModal} title={t('cam.add')} icon="camera">
	<div class="g">
		<label class="f">
			<span>{t('cam.driver')} <Hint k="cam_driver" doc="cameras" /></span>
			<select class="in" bind:value={form.driver} onchange={pick}>
				{#each drivers as d (d.id)}<option value={d.id} disabled={d.status !== 'running'}>{tx(d.name)}{d.status !== 'running' ? ` (${t(`es.${d.status}`)})` : ''}</option>{/each}
			</select>
		</label>
		<label class="f"><span>{t('devs.name')} *</span><input class="in" bind:value={form.name} placeholder={t('cam.name_ph')} /></label>
		<label class="f">
			<span>{t('devs.room')}</span>
			<select class="in" bind:value={form.roomId}><option value="">{t('devs.no_room')}</option>{#each s.rooms as r (r.id)}<option value={r.id}>{r.name}</option>{/each}</select>
		</label>
		{#if drv}<DriverFields fields={drv.fields} bind:values={form.config} />{/if}
		<p class="dim sm" style="margin:0">{t('cam.add_hint')}</p>
	</div>
	{#snippet foot()}
		<button class="btn" onclick={() => addModal.hide()}>{t('a.cancel')}</button>
		<button class="btn pri" onclick={add} disabled={busy || !form.name.trim() || !drv}>{busy ? t('cam.checking') : t('a.add')}</button>
	{/snippet}
</Modal>

<Modal bind:this={storeModal} title={t('cam.storage')} icon="folder" onclose={reload}>
	<Storage bind:store />
</Modal>

<style>
	.cam-grid {
		display: grid;
		gap: 16px;
		grid-template-columns: repeat(auto-fill, minmax(min(320px, 100%), 1fr));
	}
	.cam-empty {
		display: grid;
		justify-items: center;
		gap: 10px;
	}
	.cam-empty p {
		margin: 0;
	}
	.cam-warn {
		display: flex;
		gap: 10px;
		align-items: center;
		color: var(--warn);
		margin-bottom: 16px;
	}
</style>
