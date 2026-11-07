<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { dndzone, setAriaStrings } from 'svelte-dnd-action';
	import { useApp } from '#lib/app.svelte.js';
	import Icon from '#lib/components/Icon.svelte';
	import Hint from '#lib/components/Hint.svelte';
	import Modal from '#lib/components/Modal.svelte';
	import Widget from '#lib/components/Widget.svelte';
	import { capName, numCaps } from '#lib/devices.js';

	const app = useApp();
	const { s, t } = app;
	const GROUPS = [
		['w.g_devices', ['device', 'sensor', 'plug', 'thermo', 'value', 'chart', 'camera']],
		['w.g_home', ['room', 'lights', 'scenes', 'attention', 'battery', 'power', 'leaks', 'doors']]
	];
	const NEEDS_DEVICE = ['device', 'sensor', 'plug', 'thermo', 'value', 'chart', 'camera'];
	const NEEDS_ROOM = ['lights', 'room'];
	const WIDE = ['chart', 'room', 'power'];
	const UNIT = 164;
	const GAP = 16;
	const HEIGHTS = [0, 1, 2, 3, 4];
	let need = $state({});
	let narrow = $state(false);
	$effect(() => {
		const mq = matchMedia('(max-width: 640px)');
		const on = () => (narrow = mq.matches);
		on();
		mq.addEventListener('change', on);
		return () => mq.removeEventListener('change', on);
	});
	const span = (w) => (w.h >= 1 && w.h <= 4 ? w.h : Math.min(4, Math.max(1, Math.ceil(((need[w.id] || UNIT) + GAP) / (UNIT + GAP)))));
	const box = (w) => span(w) * UNIT + (span(w) - 1) * GAP;
	const hName = (h) => (h ? `${h}×` : t('w.h_auto'));
	const SERVICES = ['fi.valo.openmeteo', 'fi.valo.calendar', 'fi.valo.timers', 'fi.valo.energy'];
	let catalog = $state([]);
	const tx = (x) => (x && typeof x === 'object' ? (x[app.lang] ?? x.en ?? Object.values(x)[0]) : (x ?? ''));
	const offered = $derived(catalog.filter((c) => SERVICES.includes(c.id) && !c.installed && c.manifest.widgets?.length));
	const NOT_SENSOR = new Set(['lqi', 'bri', 'ct', 'pos', 'sp', 'target', 'minutes']);
	const sensorLike = (d) => d.kind !== 'light' && d.caps.some((c) => (c.type === 'num' && !NOT_SENSOR.has(c.id)) || ['open', 'leak', 'occ', 'smoke', 'co', 'gas'].includes(c.id));
	let boards = $state([]);
	let loaded = $state(false);
	let edit = $state(false);
	let items = $state([]);
	let add = $state();
	let editing = $state(null);
	let sure = $state('');
	let sureTimer;
	function drop(w) {
		clearTimeout(sureTimer);
		if (sure !== w.id) return void ((sure = w.id), (sureTimer = setTimeout(() => (sure = ''), 3000)));
		sure = '';
		items = items.filter((x) => x.id !== w.id);
		save(items);
	}
	let nw = $state({ type: 'device', room: '', device: '', ext: '', cap: '', hours: 24, title: '', size: '', h: 0 });
	let meta = $state();
	let name = $state('');
	const board = $derived(boards.find((b) => b.id === page.params.id));
	const member = $derived(app.can('member'));
	const tag = (ws) => ws.map((w, i) => ({ ...w, id: w.id || `w${Date.now().toString(36)}${i}` }));
	const devs = $derived(Object.values(s.devices).sort((a, b) => a.name.localeCompare(b.name)));
	const pick = $derived(
		{
			thermo: devs.filter((d) => d.caps.some((c) => (c.id === 'sp' || c.id === 'target') && c.access.includes('w'))),
			plug: devs.filter((d) => d.caps.some((c) => c.id === 'w')),
			sensor: devs.filter(sensorLike),
			value: devs.filter((d) => numCaps(d).length),
			chart: devs.filter((d) => numCaps(d).length),
			camera: devs.filter((d) => d.kind === 'camera')
		}[nw.type] || devs
	);
	const caps = $derived(nw.device && s.devices[nw.device] ? numCaps(s.devices[nw.device]) : []);
	$effect(() => {
		if (NEEDS_DEVICE.includes(nw.type) && !pick.some((d) => d.id === nw.device)) nw.device = pick[0]?.id || '';
	});
	$effect(() => {
		if (!caps.some((c) => c.id === nw.cap)) nw.cap = (caps.find((c) => ['t', 'w', 'h', 'kwh'].includes(c.id)) || caps[0])?.id || '';
	});
	$effect(() => {
		if (NEEDS_ROOM.includes(nw.type) && !s.rooms.some((r) => r.id === nw.room)) nw.room = s.rooms[0]?.id || '';
	});
	const ready = $derived(
		(NEEDS_ROOM.includes(nw.type) ? !!nw.room : true) &&
			(NEEDS_DEVICE.includes(nw.type) ? !!nw.device : true) &&
			(['value', 'chart'].includes(nw.type) ? !!nw.cap : true) &&
			(nw.type === 'ext' ? !!nw.ext : true)
	);
	const defOf = (ext, key) => s.contrib?.widgets?.find((c) => c.ext === ext && c.key === key);
	const hasPlace = (c) => !!c?.params?.some((x) => x.type === 'place');
	const extDef = $derived(nw.type === 'ext' && nw.ext ? defOf(JSON.parse(nw.ext).ext, JSON.parse(nw.ext).key) : null);
	const wantsPlace = $derived(hasPlace(extDef));
	let placeQ = $state('');
	let placeRes = $state([]);
	let placeBusy = $state(false);
	let placeNone = $state(false);
	const samePlace = (p) => nw.place && Math.abs(nw.place.lat - p.lat) < 0.01 && Math.abs(nw.place.lon - p.lon) < 0.01;
	async function findPlace() {
		const q = placeQ.trim();
		if (q.length < 2 || !extDef) return;
		placeBusy = true;
		const r = await app.run(() => app.api('POST', `/extensions/${extDef.ext}/page/geocode`, { q, lang: app.lang }));
		placeBusy = false;
		placeRes = r?.places || [];
		placeNone = !!r && !placeRes.length;
	}
	function openAdd(w = null) {
		editing = w?.id ?? null;
		placeQ = '';
		placeRes = [];
		placeNone = false;
		nw = w
			? { type: w.type, room: w.room || '', device: w.device || '', ext: w.type === 'ext' ? JSON.stringify({ ext: w.ext, key: w.key }) : '', cap: w.cap || '', hours: w.hours || 24, place: w.place || null, title: w.title || '', size: w.size || '', h: w.h || 0 }
			: { type: 'device', room: '', device: '', ext: '', cap: '', hours: 24, place: null, title: '', size: '', h: 0 };
		app.api('GET', '/extensions/catalog').then((c) => (catalog = c)).catch((e) => console.warn('catalog failed', e?.message));
		add.show();
	}
	function choose(type, ext = '') {
		nw.type = type;
		nw.ext = ext;
		if (!editing) nw.size = WIDE.includes(type) ? 'wide' : '';
	}
	function resize(w) {
		items = items.map((x) => (x.id === w.id ? { ...x, size: x.size === 'wide' ? undefined : 'wide' } : x));
		save(items);
	}
	function tall(w) {
		const next = HEIGHTS[(HEIGHTS.indexOf(w.h || 0) + 1) % HEIGHTS.length];
		items = items.map((x) => (x.id === w.id ? { ...x, h: next || undefined } : x));
		save(items);
	}

	$effect(() => {
		items = tag(board?.widgets || []);
	});
	const label = (w) =>
		w.title?.trim() ||
		(w.device && s.devices[w.device]?.name) ||
		(w.room && s.rooms.find((r) => r.id === w.room)?.name) ||
		(w.type === 'ext' && tx(defOf(w.ext, w.key)?.name)) ||
		t(`w.${w.type}`);
	const autoTitle = $derived(
		label({
			type: nw.type,
			device: NEEDS_DEVICE.includes(nw.type) ? nw.device : '',
			room: NEEDS_ROOM.includes(nw.type) ? nw.room : '',
			...(nw.type === 'ext' && nw.ext ? JSON.parse(nw.ext) : {})
		})
	);
	const moved = ({ itemLabel, position, count }) => t('dnd.moved', { item: itemLabel, pos: position, count });
	$effect(() => {
		app.lang;
		setAriaStrings({
			dragStarted: ({ itemLabel, zoneLabel }) => t('dnd.started', { item: itemLabel, zone: zoneLabel }),
			movedToPosition: moved,
			movedToZoneEnd: moved,
			movedToZoneStart: moved,
			dropped: ({ itemLabel }) => t('dnd.dropped', { item: itemLabel }),
			zoneActiveInstruction: t('dnd.active'),
			zoneDragDisabledInstruction: t('dnd.disabled')
		});
	});
	onMount(() => {
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
	const save = (widgets) => app.run(() => app.api('PATCH', `/dashboards/${board.id}`, { widgets: widgets.map(({ isDndShadowItem, ...w }) => w) }));
	function addWidget() {
		const w = { type: nw.type };
		if (NEEDS_ROOM.includes(nw.type)) w.room = nw.room;
		if (NEEDS_DEVICE.includes(nw.type)) w.device = nw.device;
		if (['value', 'chart'].includes(nw.type)) w.cap = nw.cap;
		if (nw.type === 'chart') w.hours = +nw.hours;
		if (nw.size === 'wide') w.size = 'wide';
		if (nw.h) w.h = nw.h;
		if (nw.type === 'ext') Object.assign(w, JSON.parse(nw.ext));
		if (wantsPlace && nw.place) w.place = { name: nw.place.name, lat: nw.place.lat, lon: nw.place.lon };
		if (nw.title.trim()) w.title = nw.title.trim().slice(0, 60);
		const old = editing && items.find((x) => x.id === editing);
		items = old ? items.map((x) => (x.id === editing ? { ...w, id: x.id } : x)) : tag([...items, w]);
		save(items);
		add.hide();
	}
	async function saveMeta() {
		if (await app.run(() => app.api('PATCH', `/dashboards/${board.id}`, { name }))) meta.hide();
	}
	let delSure = $state(false);
	let delTimer;
	async function del() {
		clearTimeout(delTimer);
		if (!delSure) return void ((delSure = true), (delTimer = setTimeout(() => (delSure = false), 3000)));
		delSure = false;
		if (await app.run(() => app.api('DELETE', `/dashboards/${board.id}`), t('board.deleted'))) (meta.hide(), goto(app.path('/boards')));
	}
	function openMeta() {
		name = board.name;
		meta.show();
	}
</script>

<svelte:head><title>{board?.name ?? t('nav.boards')} · valo</title></svelte:head>

{#if loaded && !board}
	<div class="empty">{t('board.missing')} <a href={app.path('/boards')}>{t('nav.boards')}</a></div>
{:else if board}
	<div class="ph">
		<div class="row" style="gap:12px;flex-wrap:nowrap;min-width:0">
			<a class="btn ghost" href={app.path('/boards')} aria-label={t('a.back')} title={t('nav.boards')}><Icon name="back" size={16} /></a>
			<div style="min-width:0"><h1>{board.name} <Hint k="p_boards" doc="boards" /></h1><p>{t('board.count', { n: items.length })}</p></div>
		</div>
		{#if member}
			<div class="row">
				<button class="btn" class:on={edit} onclick={() => (edit = !edit)}><Icon name="edit" size={16} />{edit ? t('a.done') : t('board.edit')}</button>
				{#if edit}<button class="btn" onclick={() => openAdd()}><Icon name="plus" size={16} />{t('board.add_widget')}</button><button class="btn ghost" onclick={openMeta}><Icon name="sliders" size={16} />{t('board.settings')}</button>{/if}
			</div>
		{/if}
	</div>
	<div class="wg wgrid" aria-label={board.name} use:dndzone={{ items, flipDurationMs: 150, dragDisabled: !edit, dropTargetStyle: {} }} onconsider={(e) => (items = e.detail.items)} onfinalize={(e) => ((items = e.detail.items), save(items))}>
		{#each items as w (w.id)}
			<div class="w" class:edit class:wide={w.size === 'wide'} style:grid-row="span {span(w)}" aria-label={label(w)}>
				<Widget {w} box={narrow ? 0 : box(w)} onneed={(px) => need[w.id] !== px && (need[w.id] = px)} />
				{#if edit}
					<div class="wtools">
						<button class="ib" aria-label={t('w.settings')} title={t('w.settings')} onclick={() => openAdd(w)}><Icon name="sliders" size={16} /></button>
						<button class="ib" aria-label={t('w.width_is', { v: w.size === 'wide' ? '2×' : '1×' })} title={t('w.width_is', { v: w.size === 'wide' ? '2×' : '1×' })} onclick={() => resize(w)}><Icon name="width" size={14} /><b class="wx">{w.size === 'wide' ? '2×' : '1×'}</b></button>
						<button class="ib" aria-label={t('w.height_is', { v: hName(w.h) })} title={t('w.height_is', { v: hName(w.h) })} onclick={() => tall(w)}><Icon name="height" size={14} /><b class="wx">{w.h ? `${w.h}×` : t('w.h_auto')}</b></button>
						<button class="ib" class:sure={sure === w.id} aria-label={sure === w.id ? t('a.confirm_delete') : t('a.delete')} title={sure === w.id ? t('a.confirm_delete') : t('a.delete')} onclick={() => drop(w)}><Icon name={sure === w.id ? 'trash' : 'x'} size={16} /></button>
					</div>
				{/if}
			</div>
		{/each}
	</div>
	{#if !items.length}<div class="empty">{t('board.empty')}</div>{/if}
{/if}

<Modal bind:this={add} title={editing ? t('w.settings') : t('board.add_widget')}>
	{#each GROUPS as [g, types]}
		<div class="lbl">{t(g)}</div>
		<div class="seg" style="flex-wrap:wrap">{#each types as k}<button class:on={nw.type === k} aria-pressed={nw.type === k} onclick={() => choose(k)}>{t(`w.${k}`)}</button>{/each}</div>
	{/each}
	<div class="lbl">{t('w.g_services')}</div>
	<div class="seg" style="flex-wrap:wrap">
		<button class:on={nw.type === 'clock'} aria-pressed={nw.type === 'clock'} onclick={() => choose('clock')}>{t('w.clock')}</button>
		{#each s.contrib?.widgets || [] as c (c.ext + c.key)}
			{@const v = JSON.stringify({ ext: c.ext, key: c.key })}
			<button class:on={nw.type === 'ext' && nw.ext === v} aria-pressed={nw.type === 'ext' && nw.ext === v} onclick={() => choose('ext', v)}>{tx(c.name)}</button>
		{/each}
	</div>
	{#if offered.length}
		<p class="sm dim" style="margin:0">{t('w.more_services')} {#each offered as c, i (c.id)}<a href={app.path(`/extensions?open=${c.id}`)}>{tx(c.manifest.name)}</a>{i < offered.length - 1 ? ', ' : ''}{/each}</p>
	{/if}
	<p class="sm dim" style="margin:0">{t(`wh.${nw.type}`)}</p>
	<label class="f">{t('w.title')}<input class="in" bind:value={nw.title} maxlength="60" placeholder={autoTitle} /></label>
	<div class="row" style="gap:16px;flex-wrap:wrap">
		<div class="f">
			{t('w.width')}
			<div class="seg" role="group" aria-label={t('w.width')}>{#each [['', '1×'], ['wide', '2×']] as [v, l]}<button class:on={nw.size === v} aria-pressed={nw.size === v} onclick={() => (nw.size = v)}>{l}</button>{/each}</div>
		</div>
		<div class="f">
			{t('w.height')}
			<div class="row" style="gap:6px;flex-wrap:nowrap"><div class="seg" role="group" aria-label={t('w.height')}>{#each HEIGHTS as h}<button class:on={nw.h === h} aria-pressed={nw.h === h} onclick={() => (nw.h = h)}>{hName(h)}</button>{/each}</div><Hint k="w_size" doc="boards" /></div>
		</div>
	</div>
	{#if wantsPlace}
		<div class="f">
			{t('w.place')}
			<div class="row" style="gap:6px;flex-wrap:nowrap">
				<input class="in" bind:value={placeQ} placeholder={t('w.place_search')} aria-label={t('w.place_search')} onkeydown={(e) => e.key === 'Enter' && (e.preventDefault(), findPlace())} />
				<button class="btn" disabled={placeQ.trim().length < 2 || placeBusy} onclick={findPlace}><Icon name="search" size={16} />{t('a.search')}</button>
			</div>
			<div class="lst">
				<button class="opt" class:on={!nw.place} aria-pressed={!nw.place} onclick={() => (nw.place = null)}><span class="dico"><Icon name="home" size={16} /></span><span>{t('w.place_home')}</span></button>
				{#if nw.place && !placeRes.some(samePlace)}<button class="opt on" aria-pressed="true"><span class="dico"><Icon name="cloud" size={16} /></span><span>{nw.place.name}</span></button>{/if}
				{#each placeRes as p (`${p.lat},${p.lon}`)}
					<button class="opt" class:on={samePlace(p)} aria-pressed={samePlace(p)} onclick={() => (nw.place = { name: p.name, lat: p.lat, lon: p.lon })}><span class="dico"><Icon name="cloud" size={16} /></span><span>{p.name}<small class="dim" style="display:block">{[p.admin, p.country].filter(Boolean).join(', ')}</small></span></button>
				{/each}
			</div>
			{#if placeNone}<span class="sm dim">{t('w.place_none')}</span>{/if}
		</div>
	{/if}
	{#if NEEDS_ROOM.includes(nw.type)}
		<label class="f">{t('devs.room')}<select class="in" bind:value={nw.room}>{#each s.rooms as r (r.id)}<option value={r.id}>{r.name}</option>{/each}</select></label>
	{:else if NEEDS_DEVICE.includes(nw.type)}
		<label class="f">{t('w.device')}<select class="in" bind:value={nw.device}>{#each pick as d (d.id)}<option value={d.id}>{d.name}</option>{:else}<option value="">-</option>{/each}</select></label>
		{#if ['value', 'chart'].includes(nw.type)}
			<label class="f">{t('prm.cap')}<select class="in" bind:value={nw.cap}>{#each caps as c (c.id)}<option value={c.id}>{capName(t, c)}</option>{/each}</select></label>
		{/if}
		{#if nw.type === 'chart'}
			<label class="f">{t('prm.span')}<select class="in" bind:value={nw.hours}>{#each [[24, 'dev.h24'], [168, 'dev.d7'], [720, 'dev.d30']] as [h, l]}<option value={h}>{t(l)}</option>{/each}</select></label>
		{/if}
	{/if}
	{#snippet foot()}
		<button class="btn" onclick={() => add.hide()}>{t('a.cancel')}</button>
		<button class="btn pri" disabled={!ready} onclick={addWidget}>{editing ? t('a.save') : t('a.add')}</button>
	{/snippet}
</Modal>

<Modal bind:this={meta} title={t('board.settings')}>
	<label class="f">{t('board.name')}<input class="in" bind:value={name} /></label>
	<div><button class="btn danger" onclick={del}><Icon name="trash" size={16} />{delSure ? t('a.confirm_delete') : t('board.delete')}</button></div>
	{#snippet foot()}
		<button class="btn" onclick={() => meta.hide()}>{t('a.cancel')}</button>
		<button class="btn pri" disabled={!name.trim()} onclick={saveMeta}>{t('a.save')}</button>
	{/snippet}
</Modal>
