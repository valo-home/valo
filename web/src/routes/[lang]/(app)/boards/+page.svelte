<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { useApp } from '#lib/app.svelte.js';
	import Icon from '#lib/components/Icon.svelte';
	import Hint from '#lib/components/Hint.svelte';
	import Modal from '#lib/components/Modal.svelte';

	const app = useApp();
	const { s, t } = app;
	const ICON = {
		device: 'dev',
		sensor: 'thermo',
		plug: 'plug',
		thermo: 'trv',
		value: 'sliders',
		chart: 'chart',
		room: 'rooms',
		lights: 'bulb',
		scenes: 'play',
		attention: 'warn',
		battery: 'battery',
		power: 'bolt',
		leaks: 'drop',
		doors: 'door',
		clock: 'clock',
		ext: 'ext'
	};
	const SHOW = 6;
	let boards = $state([]);
	let loaded = $state(false);
	let meta = $state();
	let name = $state('');
	const member = $derived(app.can('member'));
	const tx = (x) => (x && typeof x === 'object' ? (x[app.lang] ?? x.en ?? Object.values(x)[0]) : (x ?? ''));
	const extName = (w) => tx(s.contrib?.widgets?.find((c) => c.ext === w.ext && c.key === w.key)?.name) || t('w.ext');
	const label = (w) =>
		(w.device && s.devices[w.device]?.name) || (w.room && s.rooms.find((r) => r.id === w.room)?.name) || (w.type === 'ext' ? extName(w) : t(`w.${w.type}`));

	onMount(() => {
		const old = page.url.searchParams.get('board');
		if (old) return void goto(app.path(`/boards/${encodeURIComponent(old)}`), { replaceState: true });
		app.api('GET', '/dashboards')
			.then((b) => (boards = b))
			.catch((e) => app.toast(e.message, 'crit'))
			.finally(() => (loaded = true));
		const offs = [
			app.on('dashboard', (b) => (boards = boards.some((x) => x.id === b.id) ? boards.map((x) => (x.id === b.id ? b : x)) : [...boards, b])),
			app.on('dashboard_gone', (b) => (boards = boards.filter((x) => x.id !== b.id)))
		];
		return () => offs.forEach((fn) => fn());
	});
	function openNew() {
		name = '';
		meta.show();
	}
	async function create() {
		const r = await app.run(() => app.api('POST', '/dashboards', { name, widgets: [] }));
		if (r) (meta.hide(), goto(app.path(`/boards/${encodeURIComponent(r.id)}`)));
	}
</script>

<svelte:head><title>{t('nav.boards')} · valo</title></svelte:head>

<div class="ph">
	<div><h1>{t('nav.boards')} <Hint k="p_boards" doc="boards" /></h1><p>{t('board.sub')}</p></div>
	{#if member}<button class="btn pri" onclick={openNew}><Icon name="plus" size={16} />{t('board.new')}</button>{/if}
</div>

<div class="wg">
	{#each boards as b (b.id)}
		<a class="card g bcard" href={app.path(`/boards/${encodeURIComponent(b.id)}`)}>
			<h3><Icon name="grid" size={16} /><span class="bn">{b.name}</span><span class="sp"></span><Icon name="chev" size={16} /></h3>
			<div class="sm dim">{t('board.count', { n: b.widgets.length })}</div>
			{#if b.widgets.length}
				<div class="wl">
					{#each b.widgets.slice(0, SHOW) as w, i (w.id || i)}<span class="chip"><Icon name={ICON[w.type] || 'grid'} size={12} />{label(w)}</span>{/each}
					{#if b.widgets.length > SHOW}<span class="chip">+{b.widgets.length - SHOW}</span>{/if}
				</div>
			{/if}
		</a>
	{:else}
		{#if loaded}<div class="empty">{t('board.none')}</div>{/if}
	{/each}
</div>

<Modal bind:this={meta} title={t('board.new')}>
	<input class="in" bind:value={name} aria-label={t('board.name')} placeholder={t('board.name')} />
	{#snippet foot()}
		<button class="btn" onclick={() => meta.hide()}>{t('a.cancel')}</button>
		<button class="btn pri" disabled={!name.trim()} onclick={create}>{t('a.create')}</button>
	{/snippet}
</Modal>

<style>
	.bcard {
		gap: 10px;
		align-content: start;
		color: inherit;
		text-decoration: none;
		transition: border-color 0.15s;
	}
	.bcard:hover,
	.bcard:focus-visible {
		border-color: var(--amber);
	}
	.bn {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.wl {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.wl .chip {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		max-width: 100%;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
</style>
