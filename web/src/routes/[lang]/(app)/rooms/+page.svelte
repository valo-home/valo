<script>
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { useApp } from '#lib/app.svelte.js';
	import { isOn, lowBat } from '#lib/devices.js';
	import Icon from '#lib/components/Icon.svelte';
	import Hint from '#lib/components/Hint.svelte';
	import Modal from '#lib/components/Modal.svelte';
	import PlanEditor from '#lib/components/PlanEditor.svelte';
	import RoomPanel from '#lib/components/RoomPanel.svelte';

	const app = useApp();
	const { s, t, f } = app;
	const devs = $derived(Object.values(s.devices));
	const floors = $derived([...new Set(s.rooms.map((r) => r.floor))].sort());
	let room = $state(null);
	let drawer = $state();
	let editor = $state();
	let form = $state({});
	let sure = $state(false);
	let planFloor = $state(null);

	function info(r) {
		const ds = devs.filter((d) => d.roomId === r.id);
		const c = ds.find((d) => d.kind === 'clim' && d.state.t != null) || ds.find((d) => ['trv', 'floor', 'sauna'].includes(d.kind) && d.state.t != null);
		const L = ds.filter((d) => d.kind === 'light');
		const al = ds.filter((d) => !d.available || lowBat(d) || d.state.leak || (d.kind === 'contact' && d.state.open));
		return { ds, c, L, al };
	}
	const open = (r) => ((room = r), drawer.show());
	function edit(r) {
		form = r ? { ...r, geom: { x: 0, y: 0, w: 0, h: 0, ...r.geom } } : { name: '', floor: floors[0] ?? 1, outdoor: false, geom: { x: 20, y: 20, w: 160, h: 140 } };
		sure = false;
		editor.show();
	}
	async function save() {
		const body = { name: form.name.trim(), floor: +form.floor, outdoor: !!form.outdoor, geom: Object.fromEntries(Object.entries(form.geom).map(([k, v]) => [k, +v])) };
		const ok = await app.run(() => (form.id ? app.api('PATCH', `/rooms/${form.id}`, body) : app.api('POST', '/rooms', body)), t('rooms.saved'));
		if (ok) editor.hide();
	}
	async function del() {
		if (!sure) return void (sure = true);
		if (await app.run(() => app.api('DELETE', `/rooms/${form.id}`), t('rooms.deleted'))) editor.hide();
	}
	onMount(() => {
		const id = page.url.searchParams.get('room');
		const r = id && s.rooms.find((x) => x.id === id);
		if (r) open(r);
	});
</script>

<svelte:head><title>{t('nav.rooms')} · valo</title></svelte:head>

<div class="ph">
	<div><h1>{t('nav.rooms')} <Hint k="p_rooms" doc="home" /></h1><p>{t('rooms.sub', { n: s.rooms.length, f: floors.length })}</p></div>
	{#if app.can('admin')}<button class="btn pri" onclick={() => edit(null)}><Icon name="plus" size={16} />{t('rooms.add')}</button>{/if}
</div>
{#each floors as fl}
	<div class="row" style="margin:16px 0 10px;justify-content:space-between">
		<span class="lbl">{t('home.floor', { n: fl })}</span>
		{#if app.can('admin') && planFloor !== fl}<button class="btn s" onclick={() => (planFloor = fl)}><Icon name="edit" size={14} />{t('rooms.plan_edit')}</button>{/if}
	</div>
	{#if planFloor === fl}
		{#key fl}<PlanEditor floor={fl} onclose={() => (planFloor = null)} />{/key}
	{/if}
	<div class="wg" hidden={planFloor === fl}>
		{#each s.rooms.filter((r) => r.floor === fl) as r (r.id)}
			{@const x = info(r)}
			<button class="card" style="text-align:left;display:grid;gap:10px" onclick={() => open(r)}>
				<div class="row" style="justify-content:space-between"><b style="font-size:16px;font-weight:600">{r.name}</b>{#if r.outdoor}<span class="chip">{t('rooms.outdoor')}</span>{/if}</div>
				<div class="row" style="gap:18px">
					<span><span class="lbl">{t('rooms.temp')}</span><br /><b style="font-size:22px;font-weight:300" class="num">{x.c ? `${f.n(x.c.state.t, 1)}°` : '-'}</b></span>
					<span><span class="lbl">{t('home.lights')}</span><br /><b style="font-size:22px;font-weight:300" class="num">{t('home.of', { a: x.L.filter(isOn).length, b: x.L.length })}</b></span>
					<span><span class="lbl">{t('rooms.devices')}</span><br /><b style="font-size:22px;font-weight:300" class="num">{x.ds.length}</b></span>
				</div>
				<div class="row">
					{#each x.al as d (d.id)}<span class="chip {d.available && !d.state.leak ? 'warn' : 'crit'}">{d.name}</span>{:else}<span class="chip ok">{t('rooms.ok')}</span>{/each}
				</div>
			</button>
		{/each}
	</div>
{/each}

<Modal bind:this={drawer} kind="drawer" icon="rooms" title={room?.name ?? ''} sub={room ? t('home.floor', { n: room.floor }) : ''}>
	{#if room}
		<RoomPanel {room} onnav={() => drawer.hide()} onpair={() => (drawer.hide(), app.pair?.(room))} />
		{#if app.can('admin')}<button class="btn ghost" onclick={() => (drawer.hide(), edit(room))}><Icon name="edit" size={16} />{t('rooms.edit')}</button>{/if}
	{/if}
</Modal>

<Modal bind:this={editor} title={form.id ? t('rooms.edit') : t('rooms.add')}>
	<div class="fg">
		<label class="f">{t('devs.name')}<input class="in" bind:value={form.name} /></label>
		<label class="f">{t('rooms.floor')}<input class="in" type="number" min="-2" max="20" bind:value={form.floor} /></label>
	</div>
	<label class="row sm"><input type="checkbox" bind:checked={form.outdoor} />{t('rooms.outdoor')}</label>
	<div class="lbl">{t('rooms.geom')}</div>
	<div class="fg">
		{#each ['x', 'y', 'w', 'h'] as k}<label class="f">{t(`rooms.g_${k}`)}<input class="in" type="number" bind:value={form.geom[k]} /></label>{/each}
	</div>
	{#if form.id}<div><button class="btn danger" onclick={del}><Icon name="trash" size={16} />{sure ? t('a.confirm_delete') : t('a.delete')}</button></div>{/if}
	{#snippet foot()}
		<button class="btn" onclick={() => editor.hide()}>{t('a.cancel')}</button>
		<button class="btn pri" disabled={!form.name?.trim()} onclick={save}>{t('a.save')}</button>
	{/snippet}
</Modal>
