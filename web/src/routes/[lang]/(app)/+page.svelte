<script>
	import { useApp } from '#lib/app.svelte.js';
	import { isOn, lowBat, unit } from '#lib/devices.js';
	import Feed from '#lib/components/Feed.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import Hint from '#lib/components/Hint.svelte';
	import Modal from '#lib/components/Modal.svelte';
	import Plan from '#lib/components/Plan.svelte';
	import PlanEditor from '#lib/components/PlanEditor.svelte';
	import RoomPanel from '#lib/components/RoomPanel.svelte';

	const app = useApp();
	const { s, t, f } = app;
	let planning = $state(false);
	const devs = $derived(Object.values(s.devices));
	const floors = $derived([...new Set(s.rooms.filter((r) => r.geom?.w).map((r) => r.floor))].sort());
	let floor = $state(null);
	const fl = $derived(floor ?? floors[0] ?? 1);
	let room = $state(null);
	let drawer = $state();
	const outdoor = $derived(new Set(s.rooms.filter((r) => r.outdoor).map((r) => r.id)));
	const lights = $derived(devs.filter((d) => d.kind === 'light'));
	const temp = (list) => (list.length ? list.reduce((a, d) => a + d.state.t, 0) / list.length : null);
	const climate = $derived(devs.filter((d) => d.kind === 'clim' && typeof d.state.t === 'number' && d.source !== 'ext'));
	const outside = $derived(temp(climate.filter((d) => outdoor.has(d.roomId))));
	const inside = $derived(temp(climate.filter((d) => d.roomId && !outdoor.has(d.roomId))));
	const usage = $derived(devs.find((d) => d.kind === 'meter' && d.source === 'ext' && typeof d.state.today_kwh === 'number'));
	const meter = $derived(devs.find((d) => d.kind === 'meter' && d.source !== 'ext' && typeof d.state.w === 'number') || usage);
	const running = $derived(s.flows.filter((x) => x.lastResult === 'run' || x.lastResult === 'wait').length);
	const attn = $derived([
		...devs.filter((d) => d.kind === 'contact' && d.state.open).map((d) => ['', 'door', t('home.open', { name: d.name }), d]),
		...devs.filter((d) => d.state.leak).map((d) => ['crit', 'drop', t('home.leak', { name: d.name }), d]),
		...devs.filter((d) => d.state.smoke).map((d) => ['crit', 'flame', t('home.smoke', { name: d.name }), d]),
		...devs.filter((d) => d.state.co || d.state.gas).map((d) => ['crit', 'warn', t(d.state.co ? 'home.co' : 'home.gas', { name: d.name }), d]),
		...devs.filter(lowBat).map((d) => ['', 'drop', t('home.battery', { name: d.name, n: d.state.bat }), d]),
		...devs.filter((d) => !d.available).map((d) => ['crit', 'warn', t('home.offline', { name: d.name }), d])
	]);
	const climRooms = $derived(
		s.rooms
			.map((r) => {
				const ds = devs.filter((d) => d.roomId === r.id);
				const m = ds.find((d) => d.kind === 'clim' && d.state.t != null) || ds.find((d) => ['trv', 'floor', 'sauna'].includes(d.kind) && d.state.t != null);
				const v = ds.find((d) => d.kind === 'trv' || d.kind === 'floor');
				return m && { r, m, v };
			})
			.filter(Boolean)
	);
	const openRoom = (r) => ((room = r), drawer.show());
	const unplaced = $derived(devs.filter((d) => !d.roomId && !d.service).length);
</script>

<div class="ph">
	<div>
		<h1>{s.home.name} <Hint k="p_home" doc="home" /></h1>
		<p>
			{f.full()}.
			{#if outside != null}{t('home.outside', { v: f.n(outside, 1) })}{/if}
			{#if inside != null}{t('home.inside', { v: f.n(inside, 1) })}{/if}
			{#if meter}{t('home.power', { v: f.n(meter.state.w / 1000, 2) })}{/if}
		</p>
	</div>
	<div class="row">
		<a class="btn" href={app.path('/boards')}><Icon name="grid" size={16} />{t('nav.boards')}</a>
		<a class="btn" href={app.path('/rooms')}><Icon name="rooms" size={16} />{t('nav.rooms')}</a>
	</div>
</div>

{#if attn.length}
	<div class="attn">
		{#each attn as [k, i, txt, d]}<a class="att {k}" href={app.path(`/devices/${encodeURIComponent(d.id)}`)}><Icon name={i} size={16} />{txt}</a>{/each}
	</div>
{/if}

<div class="home">
	<section class="card stage">
		<div class="stop">
			<div class="row" style="gap:8px">
			<div class="seg">{#each floors as x}<button class:on={fl === x} aria-pressed={!!(fl === x)} disabled={planning} onclick={() => (floor = x)}>{t('home.floor', { n: x })}</button>{/each}</div>
			{#if floors.length && app.can('admin') && !planning}<button class="btn s" onclick={() => (planning = true)}><Icon name="edit" size={14} />{t('rooms.plan_edit')}</button>{/if}
			</div>
			<div class="readout">
				<div><span class="lbl">{t('home.lights')}</span><b>{t('home.of', { a: lights.filter(isOn).length, b: lights.length })}</b></div>
				<div><span class="lbl">{t('home.opened')}</span><b>{devs.filter((d) => d.kind === 'contact' && d.state.open).length}</b></div>
				<div><span class="lbl">{t('home.leaks')}</span><b>{devs.filter((d) => d.state.leak).length || t('v.none')}</b></div>
				<div><span class="lbl">{t('home.running')}</span><b>{running}</b></div>
			</div>
		</div>
		{#if floors.length}
			{#if planning}
				{#key fl}<PlanEditor floor={fl} onclose={() => (planning = false)} />{/key}
			{:else}
				<div id="plan"><Plan floor={fl} onroom={openRoom} /></div>
			{/if}
		{:else}
			<div class="empty-plan">
				<Icon name="rooms" size={28} />
				<h3>{t('home.empty_title')}</h3>
				<p class="dim">{t('home.empty_hint')}</p>
				{#if unplaced}<p class="sm dim">{t('home.unplaced', { n: unplaced })}</p>{/if}
				<div class="row" style="justify-content:center">
					<a class="btn pri" href={app.path('/rooms')}><Icon name="rooms" size={16} />{t('home.add_rooms')}</a>
					<a class="btn" href={app.path('/devices')}><Icon name="dev" size={16} />{t('nav.devices')}</a>
				</div>
			</div>
		{/if}
		<div class="legend">
			<span><i class="dot" style="background:var(--amber)"></i>{t('home.lg_on')}</span>
			<span><i class="dot" style="background:var(--frost)"></i>{t('home.lg_motion')}</span>
			<span><i class="dot crit"></i>{t('home.lg_attn')}</span>
			<span>{t('home.lg_hint')}</span>
		</div>
	</section>
	<aside class="g">
		<section class="card">
			<h3><Icon name="layers" size={16} />{t('home.scenes')}</h3>
			<div class="scenes">
				{#each s.scenes as x (x.id)}
					<button class="scene" onclick={() => app.run(() => app.api('POST', `/scenes/${x.id}/apply`), t('scenes.applied', { name: x.name }))}><Icon name={x.icon} /><span>{x.name}</span></button>
				{:else}<span class="dim sm">{t('home.no_scenes')}</span>{/each}
			</div>
		</section>
		{#if climRooms.length}
			<section class="card">
				<h3><Icon name="thermo" size={16} />{t('home.climate')}<span class="sp"></span><span class="lbl">{t('home.now_target')}</span></h3>
				{#each climRooms as { r, m, v } (r.id)}
					<button class="ri" style="padding:7px 4px" onclick={() => openRoom(r)}>
						<span style="flex:1">{r.name}</span><span class="num"><b>{f.n(m.state.t, 1)}</b> °C</span>
						<small style="width:72px;text-align:right">{v ? t('home.target', { v: f.n(v.state.sp, 1) }) : ''}</small>
					</button>
				{/each}
			</section>
		{/if}
		{#if meter}
			<section class="card">
				<h3><Icon name="bolt" size={16} />{t('home.energy')}</h3>
				<div class="row" style="justify-content:space-between;align-items:flex-end">
					{#if usage}<div><div class="lbl">{t('cap.today_kwh')}</div><b style="font-size:24px;font-weight:300" class="num">{f.n(usage.state.today_kwh, 2)}</b> <span class="dim sm">{f.n(usage.state.today_cost, 2)} {s.home?.currency || ''}</span></div>{/if}
					<div style="text-align:right"><div class="lbl">{t('home.consumption')}</div><b style="font-size:24px;font-weight:300" class="num">{f.n(meter.state.w / 1000, 2)}</b> <span class="dim sm">{unit(t, 'kW')}</span></div>
				</div>
			</section>
		{/if}
		<section class="card">
			<h3><Icon name="log" size={16} />{t('home.pulse')}<span class="sp"></span><a class="sm" href={app.path('/log')}>{t('nav.log')}</a></h3>
			<Feed events={s.events} limit={8} />
		</section>
	</aside>
</div>

<Modal bind:this={drawer} kind="drawer" icon="rooms" title={room?.name ?? ''} sub={room ? t('home.floor', { n: room.floor }) : ''}>
	{#if room}<RoomPanel {room} onnav={() => drawer.hide()} onpair={() => (drawer.hide(), app.pair?.(room))} />{/if}
</Modal>
