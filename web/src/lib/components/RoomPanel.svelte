<script>
	import { useApp } from '#lib/app.svelte.js';
	import { icon } from '#lib/devices.js';
	import DeviceRow from './DeviceRow.svelte';
	import Icon from './Icon.svelte';

	let { room, onnav, onpair } = $props();
	const app = useApp();
	const { s, t } = app;
	const all = $derived(Object.values(s.devices).sort((a, b) => a.name.localeCompare(b.name)));
	const ds = $derived(all.filter((d) => d.roomId === room.id));
	const flows = $derived(s.flows.filter((fl) => fl.graph.nodes?.some((n) => ds.some((d) => d.id === n.params?.device))));
	const roomName = (id) => s.rooms.find((r) => r.id === id)?.name;
	let picking = $state(false);
	let chosen = $state(new Set());
	let q = $state('');
	let busy = $state(false);
	const list = $derived(
		all
			.filter((d) => !q.trim() || d.name.toLowerCase().includes(q.trim().toLowerCase()))
			.sort((a, b) => (a.roomId === room.id ? 0 : a.roomId ? 2 : 1) - (b.roomId === room.id ? 0 : b.roomId ? 2 : 1))
	);
	$effect(() => {
		room.id;
		picking = false;
		chosen = new Set();
	});
	const changes = $derived(all.filter((d) => chosen.has(d.id) !== (d.roomId === room.id)));

	function start() {
		chosen = new Set(ds.map((d) => d.id));
		q = '';
		picking = true;
	}
	function toggle(id) {
		const n = new Set(chosen);
		n.has(id) ? n.delete(id) : n.add(id);
		chosen = n;
	}
	async function apply() {
		busy = true;
		const todo = changes.map((d) => [d.id, chosen.has(d.id) ? room.id : null]);
		let done = 0;
		for (const [id, roomId] of todo) {
			const r = await app.run(() => app.api('PATCH', `/devices/${encodeURIComponent(id)}`, { roomId }));
			if (r) done++;
		}
		busy = false;
		if (done) app.toast(t('rooms.assigned', { n: done }));
		if (done === todo.length) picking = false;
	}
</script>

{#if picking}
	<p class="sm dim" style="margin:0">{t('rooms.pick_hint')}</p>
	<input class="in" type="search" bind:value={q} placeholder={t('rooms.pick_search')} aria-label={t('rooms.pick_search')} />
	<div class="lst" style="max-height:min(52vh,460px);overflow:auto">
		{#each list as d (d.id)}
			<label class="ri pick">
				<input type="checkbox" checked={chosen.has(d.id)} onchange={() => toggle(d.id)} />
				<Icon name={icon(d)} size={16} />
				<span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{d.name}</span>
				<small>{d.roomId === room.id ? '' : d.roomId ? t('rooms.in_room', { room: roomName(d.roomId) || d.roomId }) : t('rooms.no_room')}</small>
			</label>
		{:else}<p class="dim">{t('rooms.no_devices')}</p>{/each}
	</div>
	<div class="row">
		<button class="btn" onclick={() => (picking = false)}>{t('a.cancel')}</button>
		<button class="btn pri" disabled={!changes.length || busy} onclick={apply}>{busy ? '...' : t('a.save')}{changes.length ? ` (${changes.length})` : ''}</button>
	</div>
{:else}
	<div class="lst">
		{#each ds as d (d.id)}<DeviceRow {d} {onnav} />{:else}<p class="dim">{t('rooms.empty')}</p>{/each}
	</div>
	{#if app.can('admin')}
		<div class="row">
			<button class="btn pri" onclick={start} disabled={!all.length}><Icon name="plus" size={16} />{t('rooms.pick')}</button>
			{#if onpair}<button class="btn" onclick={onpair}><Icon name="zig" size={16} />{t('rooms.pair_new')}</button>{/if}
		</div>
	{/if}
	<div>
		<div class="lbl" style="margin-bottom:8px">{t('rooms.flows')}</div>
		<div class="lst">
			{#each flows as fl (fl.id)}
				<a class="ri" href={app.path(`/flows/${fl.id}`)} onclick={onnav}><Icon name="flow" size={16} />{fl.name}<small>{t(`res.${fl.lastResult || 'none'}`)}</small></a>
			{:else}<span class="dim sm">{t('rooms.noflows')}</span>{/each}
		</div>
	</div>
{/if}
