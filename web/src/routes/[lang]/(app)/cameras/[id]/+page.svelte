<script>
	import { onMount, untrack } from 'svelte';
	import { page } from '$app/state';
	import { useApp } from '#lib/app.svelte.js';
	import CameraLive from '#lib/components/CameraLive.svelte';
	import CameraPtz from '#lib/components/CameraPtz.svelte';
	import CameraStatus from '#lib/components/CameraStatus.svelte';
	import CameraTimeline from '#lib/components/CameraTimeline.svelte';
	import Hint from '#lib/components/Hint.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import Modal from '#lib/components/Modal.svelte';

	const app = useApp();
	const { s, t, f } = app;
	const tx = (x) => (x && typeof x === 'object' ? (x[app.lang] ?? x.en ?? Object.values(x)[0]) : (x ?? ''));
	const id = $derived(page.params.id);
	const enc = $derived(encodeURIComponent(page.params.id));
	const admin = $derived(app.can('admin'));
	const TABS = ['events', 'media', 'timeline'];
	let cam = $state(null);
	let missing = $state(false);
	let events = $state([]);
	let media = $state([]);
	let days = $state([]);
	let day = $state('');
	let pieces = $state([]);
	let dayEvents = $state([]);
	let more = $state({ ev: true, md: true });
	let tab = $state(TABS.includes(page.url.searchParams.get('tab')) ? page.url.searchParams.get('tab') : 'events');
	let kind = $state('');
	let label = $state('');
	let sub = $state(false);
	let muted = $state(true);
	let aim = $state(false);
	let ptzc = $state();
	let liveBox = $state();
	let view = $state(null);
	let viewer = $state();
	let player = $state();
	let picking = $state(false);
	let picked = $state([]);
	let sure = $state('');
	let bulk = $state();
	let bulkWhat = $state('');
	const d = $derived(cam ? s.devices[cam.deviceId] : null);
	const room = $derived(s.rooms.find((r) => r.id === d?.roomId)?.name || '');
	const online = $derived(d ? d.available : !!cam?.available);
	const code = $derived(cam?.status?.code || 'ok');
	const live = $derived(online && !['offline', 'other_device', 'auth_api', 'auth_stream', 'driver_stopped'].includes(code));
	const moving = $derived(!!d?.state?.occ);
	const ptz = $derived(!!cam?.ptz && cam?.features?.includes('ptz'));
	const LABEL = (l) => (t.has(`cam.l_${l}`) ? t(`cam.l_${l}`) : l);
	const dur = (a, b) => (a && b ? Math.max(0, Math.round((new Date(b) - new Date(a)) / 1000)) : null);
	const today = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);
	const labels = $derived([...new Set(['motion', ...events.map((e) => e.label)])]);
	const tlDay = $derived(day || today());
	const recMode = $derived(
		cam ? (cam.record.mode === 'events' ? t('cam.rec_events', { pre: cam.record.pre, post: cam.record.post }) : cam.record.mode === 'continuous' ? t('cam.rec_continuous', { n: cam.record.keep_days }) : t(cam.record.snapshots === false ? 'cam.rec_none' : 'cam.rec_off')) : ''
	);

	async function load() {
		try {
			cam = await app.api('GET', `/cameras/${enc}`);
			missing = false;
		} catch (e) {
			missing = true;
			console.warn('camera load failed', id, e?.message);
			return;
		}
		await Promise.all([loadEvents(true), loadMedia(true), loadDays()]).catch((e) => app.toast(e.message, 'crit'));
	}
	async function refresh() {
		cam = await app.api('GET', `/cameras/${enc}`).catch((e) => (console.warn('camera reload failed', e?.message), cam));
	}
	const more_ = (fn) => fn().catch((e) => app.toast(e.message, 'crit'));
	async function loadDays() {
		days = await app.api('GET', `/media/days?camera=${enc}`);
	}
	async function loadEvents(fresh = false) {
		const last = fresh ? '' : events.at(-1)?.id || '';
		const q = new URLSearchParams({ ...(last ? { before: String(last) } : {}), ...(day ? { day } : {}), ...(label ? { label } : {}) });
		const r = await app.api('GET', `/cameras/${enc}/events?${q}`);
		events = fresh ? r : [...events, ...r];
		more.ev = r.length >= 50;
	}
	async function loadMedia(fresh = false) {
		const last = fresh ? '' : media.at(-1)?.createdAt || '';
		const q = new URLSearchParams({ camera: id, limit: '60', ...(kind ? { kind } : {}), ...(day ? { day } : {}), ...(last ? { before: last } : {}) });
		const r = await app.api('GET', `/media?${q}`);
		media = fresh ? r : [...media, ...r];
		more.md = r.length >= 60;
	}
	async function loadTimeline() {
		const q = new URLSearchParams({ camera: id, kind: 'video', day: tlDay, limit: '200' });
		const [m, e] = await Promise.all([app.api('GET', `/media?${q}`), app.api('GET', `/cameras/${enc}/events?day=${tlDay}&limit=500`)]);
		pieces = m.filter((x) => x.origin === 'continuous').reverse();
		dayEvents = e;
	}
	$effect(() => {
		id;
		cam = null;
		load();
	});
	let shown = '';
	$effect(() => {
		const k = `${kind}|${day}|${label}`;
		if (k === shown) return;
		const first = !shown;
		shown = k;
		if (first || !untrack(() => cam)) return;
		picked = [];
		Promise.all([loadMedia(true), loadEvents(true)]).catch((e) => app.toast(e.message, 'crit'));
	});
	$effect(() => {
		if (tab === 'timeline' && cam) untrack(() => loadTimeline().catch((e) => app.toast(e.message, 'crit')));
	});
	$effect(() => {
		const u = new URL(page.url);
		if (u.searchParams.get('tab') === tab) return;
		u.searchParams.set('tab', tab);
		history.replaceState(history.state, '', u);
	});
	onMount(() => {
		const off = [
			app.on('camera_event', (e) => {
				if (e?.cameraId !== id) return;
				const i = events.findIndex((x) => x.id === e.id);
				if (i >= 0) events[i] = e;
				else if (!day && (!label || label === e.label)) events = [e, ...events];
			}),
			app.on('camera_event_gone', (e) => (events = events.filter((x) => x.id !== e?.id))),
			app.on('media', (m) => {
				if (m?.cameraId !== id) return;
				const i = media.findIndex((x) => x.id === m.id);
				if (i >= 0) media[i] = { ...media[i], ...m };
				else if (!day && (!kind || m.kind === kind)) media = [m, ...media];
			}),
			app.on('media_gone', (m) => {
				const gone = new Set(m?.ids || [m?.id]);
				media = media.filter((x) => !gone.has(x.id));
				picked = picked.filter((x) => !gone.has(x));
			}),
			app.on('device', (x) => x?.id === cam?.deviceId && refresh())
		];
		return () => off.forEach((x) => x());
	});

	const snap = () => app.run(() => app.api('POST', `/cameras/${enc}/snapshot`), t('cam.snap_saved'));
	const clip = () => app.run(() => app.api('POST', `/cameras/${enc}/clip`, { seconds: 30 }), t('cam.clip_started', { n: 30 }));
	const full = () => liveBox?.requestFullscreen?.().catch((e) => console.warn('fullscreen refused', e?.message));
	function open(m, offset = 0) {
		view = { ...m, offset };
		viewer.show();
	}
	function seek() {
		if (player && view?.offset) player.currentTime = view.offset;
	}
	function step(dir) {
		const list = media;
		const i = list.findIndex((x) => x.id === view?.id);
		const next = list[i + dir];
		if (next) view = { ...next, offset: 0 };
	}
	function aimAt(ev) {
		if (!aim || !ptzc) return;
		const r = ev.currentTarget.getBoundingClientRect();
		ptzc.point((ev.clientX - r.left) / r.width, (ev.clientY - r.top) / r.height);
	}
	function pick(m) {
		picked = picked.includes(m.id) ? picked.filter((x) => x !== m.id) : [...picked, m.id];
	}
	async function keep(m, on) {
		const r = await app.run(() => app.api('PATCH', `/media/${m.id}`, { keep: on }), on ? t('cam.kept') : t('cam.unkept'));
		if (r?.id) {
			media = media.map((x) => (x.id === r.id ? { ...x, keep: r.keep } : x));
			if (view?.id === r.id) view = { ...view, keep: r.keep };
		}
	}
	async function drop(m) {
		if (sure !== `m${m.id}`) return void (sure = `m${m.id}`);
		sure = '';
		if (await app.run(() => app.api('DELETE', `/media/${m.id}`), t('cam.deleted', { n: 1 }))) {
			media = media.filter((x) => x.id !== m.id);
			viewer.hide();
			loadDays().catch((e) => console.warn('days reload failed', e?.message));
		}
	}
	async function dropEvent(e) {
		if (sure !== `e${e.id}`) return void (sure = `e${e.id}`);
		sure = '';
		const r = await app.run(() => app.api('DELETE', `/cameras/${enc}/events/${e.id}`));
		if (r) {
			events = events.filter((x) => x.id !== e.id);
			app.toast(t('cam.event_deleted', { n: r.deleted }));
		}
	}
	function ask(what) {
		bulkWhat = what;
		bulk.show();
	}
	async function bulkDelete() {
		const body = bulkWhat === 'picked' ? { ids: picked } : bulkWhat === 'day' ? { camera: id, day } : { camera: id, all: true };
		const r = await app.run(() => app.api('POST', '/media/delete', body));
		bulk.hide();
		if (!r) return;
		app.toast(t('cam.deleted', { n: r.deleted }) + (r.skipped ? ` ${t('cam.skipped_kept', { n: r.skipped })}` : ''));
		picked = [];
		picking = false;
		if (bulkWhat !== 'picked') day = '';
		await Promise.all([loadMedia(true), loadEvents(true), loadDays()]).catch((e) => app.toast(e.message, 'crit'));
	}
	async function bulkKeep(on) {
		for (const mid of picked) await app.api('PATCH', `/media/${mid}`, { keep: on }).catch((e) => app.toast(e.message, 'crit'));
		media = media.map((x) => (picked.includes(x.id) ? { ...x, keep: on } : x));
		app.toast(on ? t('cam.kept') : t('cam.unkept'));
	}
	const zip = () => (window.location.href = `/api/v1/media/zip?ids=${picked.join(',')}`);
	const sizeOf = $derived(media.filter((x) => picked.includes(x.id)).reduce((a, x) => a + x.size, 0));
</script>

<svelte:head><title>{d?.name ?? cam?.name ?? t('nav.cameras')} · valo</title></svelte:head>

{#if missing}
	<div class="empty">{t('cam.missing')} <a href={app.path('/cameras')}>{t('nav.cameras')}</a></div>
{:else if cam}
	<div class="ph">
		<div>
			<div class="crumbs"><a href={app.path('/cameras')}>{t('nav.cameras')}</a></div>
			<h1>{d?.name ?? cam.name}</h1>
			<p class="meta">
				{#if room}<span>{room}</span>{/if}
				<span>{tx(cam.driverName)}</span>
				{#if cam.info.model}<span>{cam.info.model}</span>{/if}
			</p>
		</div>
		<div class="row" style="flex-wrap:wrap">
			<button class="btn" onclick={snap} disabled={!live}><Icon name="image" size={16} />{t('cam.snapshot')}</button>
			<button class="btn" onclick={clip} disabled={!live}><Icon name="record" size={16} />{t('cam.clip', { n: 30 })}</button>
			<a class="btn" href={app.path(`/cameras/${enc}/settings`)}><Icon name="sliders" size={16} />{t('cam.settings')}</a>
		</div>
	</div>

	<div class="cam-top">
		<div>
			<div class="cam-view" class:aim bind:this={liveBox}>
				{#if live}
					<CameraLive camera={cam.id} {sub} {muted} poster={`/api/v1/cameras/${enc}/preview`} />
					{#if aim}<button class="cam-aim" onclick={aimAt} aria-label={t('cam.ptz_aim_hint')}></button>{/if}
					{#if ptz}<CameraPtz bind:this={ptzc} {cam} bind:aim onpresets={(r) => (cam.presets = r)} />{/if}
				{:else}
					<div class="cam-off"><CameraStatus {cam} actions={false} /></div>
				{/if}
				<div class="cam-bar">
					{#if cam.streams.includes('sub')}
						<div class="seg cam-q" role="group" aria-label={t('cam.quality')}>
							<button class:on={!sub} aria-pressed={!sub} onclick={() => (sub = false)}>HD</button>
							<button class:on={sub} aria-pressed={sub} onclick={() => (sub = true)}>SD</button>
						</div>
					{/if}
					<span style="flex:1"></span>
					<button class="ib cam-ib" onclick={() => (muted = !muted)} aria-label={muted ? t('cam.sound_on') : t('cam.sound_off')} title={muted ? t('cam.sound_on') : t('cam.sound_off')}><Icon name={muted ? 'mute' : 'volume'} size={18} /></button>
					<button class="ib cam-ib" onclick={full} aria-label={t('cam.fullscreen')} title={t('cam.fullscreen')}><Icon name="expand" size={18} /></button>
				</div>
			</div>
			{#if ptz && live}<CameraPtz {cam} bind:aim bar onpresets={(r) => (cam.presets = r)} />{/if}
		</div>
		<div class="card cam-side">
			<CameraStatus {cam} onchanged={refresh} />
			<div class="cam-state">
				<span class="dico" class:on={moving}><Icon name={moving ? 'motion' : 'camera'} size={18} /></span>
				<div>
					<b>{!live ? t('v.offline') : moving ? t('v.motion') : t('v.still')}</b>
					<small class="dim">{t('cam.last_event')}: {events[0] ? f.ago(events[0].startedAt) : '-'}</small>
				</div>
			</div>
			<dl class="kv cam-kv">
				<dt>{t('cam.recording')} <Hint k="cam_record" doc="cameras" /></dt><dd>{recMode}{#if cam.record.schedule?.mode === 'hours'}<small class="dim">{cam.record.schedule.from}-{cam.record.schedule.to}</small>{/if}</dd>
				{#if cam.video?.kbps}<dt>{t('cam.bitrate')}</dt><dd>{f.n(cam.video.kbps, 0)}&nbsp;{t('u.kbps')}</dd>{/if}
				{#if cam.video?.codecs?.length}<dt>{t('cam.codecs')}</dt><dd>{cam.video.codecs.join(', ')}</dd>{/if}
				<dt>{t('cam.streams')}</dt><dd>{cam.streams.map((x) => (x === 'main' ? 'HD' : 'SD')).join(', ')}</dd>
				{#if cam.config.host}<dt>{t('cam.address')}</dt><dd class="mono">{cam.config.host}</dd>{/if}
			</dl>
			<a class="sm" href={app.path(`/devices/${encodeURIComponent(cam.deviceId)}`)}>{t('cam.as_device')}</a>
		</div>
	</div>

	<div class="cam-days" role="group" aria-label={t('cam.days_rec')}>
		<button class="chip" class:amber={!day} aria-pressed={!day} onclick={() => (day = '')}>{t('cam.all_days')}</button>
		{#each days as x (x.day)}
			<button class="chip" class:amber={day === x.day} aria-pressed={day === x.day} onclick={() => (day = x.day)} title={f.bytes(x.size)}>{f.date(`${x.day}T12:00:00`)}<small>{x.photos + x.videos}</small></button>
		{/each}
		<input class="in cam-date" type="date" bind:value={day} aria-label={t('cam.pick_day')} />
	</div>

	<div class="tabs">
		<button class:on={tab === 'events'} aria-pressed={tab === 'events'} onclick={() => (tab = 'events')}>{t('cam.events')}</button>
		<button class:on={tab === 'media'} aria-pressed={tab === 'media'} onclick={() => (tab = 'media')}>{t('cam.media')}</button>
		<button class:on={tab === 'timeline'} aria-pressed={tab === 'timeline'} onclick={() => (tab = 'timeline')}>{t('cam.timeline')}</button>
	</div>

	{#if tab === 'events'}
		<div class="row cam-tools">
			<div class="seg" role="group" aria-label={t('cam.ev_filter')}>
				<button class:on={!label} aria-pressed={!label} onclick={() => (label = '')}>{t('cam.all')}</button>
				{#each labels as l}<button class:on={label === l} aria-pressed={label === l} onclick={() => (label = l)}>{LABEL(l)}</button>{/each}
			</div>
		</div>
		<div class="lst cam-evs">
			{#each events as e (e.id)}
				<div class="ri cam-ev">
					<button class="cam-th" onclick={() => e.snapshot && open({ kind: 'photo', url: e.snapshot, createdAt: e.startedAt })} disabled={!e.snapshot} aria-label={t('cam.photo')}>
						{#if e.snapshot}<img src={e.snapshot} alt="" loading="lazy" />{:else}<Icon name="motion" size={18} />{/if}
					</button>
					<div class="cam-evt">
						<b>{LABEL(e.label)}{#if e.score}<small class="dim"> {Math.round(e.score * 100)}%</small>{/if}</b>
						<span class="dim sm">{f.stamp(e.startedAt)}{#if e.endedAt && dur(e.startedAt, e.endedAt)}{' · '}{t('cam.sec', { n: dur(e.startedAt, e.endedAt) })}{:else if !e.endedAt}{' · '}{t('cam.now')}{/if}{#if e.source !== 'driver'}{' · '}{e.source}{/if}</span>
					</div>
					{#if e.clip}<button class="btn s" onclick={() => open({ kind: 'video', url: e.clip, createdAt: e.startedAt })}><Icon name="play" size={14} /><span class="hm">{t('cam.play')}</span></button>{/if}
					{#if admin}<button class="btn s" class:danger={sure === `e${e.id}`} onclick={() => dropEvent(e)} aria-label={t('cam.event_delete')} title={t('cam.event_delete')}><Icon name="trash" size={14} />{#if sure === `e${e.id}`}{t('a.confirm_delete')}{/if}</button>{/if}
				</div>
			{:else}
				<div class="empty">{t('cam.no_events')}</div>
			{/each}
		</div>
		{#if events.length && more.ev}<button class="btn s" style="margin-top:12px" onclick={() => more_(loadEvents)}>{t('cam.more')}</button>{/if}
	{:else if tab === 'media'}
		<div class="row cam-tools">
			<div class="seg" role="group" aria-label={t('cam.media')}>
				{#each [['', 'cam.all'], ['video', 'cam.videos'], ['photo', 'cam.photos']] as [k, l]}<button class:on={kind === k} aria-pressed={kind === k} onclick={() => (kind = k)}>{t(l)}</button>{/each}
			</div>
			<span style="flex:1"></span>
			{#if media.length}<button class="btn s" class:on={picking} aria-pressed={picking} onclick={() => ((picking = !picking), (picked = []))}><Icon name="check" size={14} />{picking ? t('a.cancel') : t('cam.select')}</button>{/if}
			{#if admin && day}<button class="btn s danger" onclick={() => ask('day')}><Icon name="trash" size={14} />{t('cam.delete_day')}</button>{/if}
			{#if admin && !day && media.length}<button class="btn s danger" onclick={() => ask('all')}><Icon name="trash" size={14} />{t('cam.delete_all')}</button>{/if}
		</div>
		{#if picking}
			<div class="row cam-pickbar">
				<b>{t('cam.picked', { n: picked.length })}</b>{#if picked.length}<span class="dim sm">{f.bytes(sizeOf)}</span>{/if}
				<span style="flex:1"></span>
				<button class="btn s" onclick={() => (picked = picked.length === media.length ? [] : media.map((x) => x.id))}>{picked.length === media.length ? t('cam.pick_none') : t('cam.pick_all')}</button>
				<button class="btn s" onclick={zip} disabled={!picked.length}><Icon name="download" size={14} />{t('a.download')}</button>
				{#if admin}
					<button class="btn s" onclick={() => bulkKeep(true)} disabled={!picked.length}><Icon name="lock" size={14} />{t('cam.keep')}</button>
					<button class="btn s" onclick={() => bulkKeep(false)} disabled={!picked.length}>{t('cam.unkeep')}</button>
					<button class="btn s danger" onclick={() => ask('picked')} disabled={!picked.length}><Icon name="trash" size={14} />{t('a.delete')}</button>
				{/if}
			</div>
		{/if}
		<div class="cam-media">
			{#each media as m (m.id)}
				<button class="cam-m" class:sel={picked.includes(m.id)} onclick={() => (picking ? pick(m) : open(m))} aria-pressed={picking ? picked.includes(m.id) : undefined}>
					<span class="cam-pic">
						{#if m.kind === 'photo'}<img src={m.url} alt="" loading="lazy" />{:else}<span class="cam-vid" style:background-image={m.thumb ? `url(${m.thumb})` : ''}><i><Icon name="play" size={20} /></i></span>{/if}
						{#if picking}<span class="cam-ck"><Icon name="check" size={14} /></span>{/if}
						{#if m.keep}<span class="cam-keep" title={t('cam.kept_hint')}><Icon name="lock" size={12} /></span>{/if}
						{#if m.origin === 'continuous'}<span class="cam-cont">{t('cam.continuous')}</span>{/if}
					</span>
					<small><span>{f.stamp(m.createdAt)}</span><span class="dim">{m.kind === 'video' && m.duration ? t('cam.sec', { n: Math.round(m.duration) }) : f.bytes(m.size)}</span></small>
				</button>
			{:else}
				<div class="empty">{t('cam.no_media')}</div>
			{/each}
		</div>
		{#if media.length && more.md}<button class="btn s" style="margin-top:12px" onclick={() => more_(loadMedia)}>{t('cam.more')}</button>{/if}
	{:else}
		<div class="card g" style="gap:12px">
			<h3><Icon name="clock" size={16} />{t('cam.timeline_day', { day: f.date(`${tlDay}T12:00:00`) })} <Hint k="cam_timeline" doc="cameras" /></h3>
			<CameraTimeline day={tlDay} {pieces} events={dayEvents} onplay={(m, off) => open(m, off)} />
			{#if !pieces.length}<p class="dim sm" style="margin:0">{cam.record.mode === 'continuous' ? t('cam.tl_empty') : t('cam.tl_off')}</p>{/if}
		</div>
	{/if}
{:else}
	<p class="dim">{t('w.loading')}</p>
{/if}

<Modal bind:this={viewer} title={view ? f.stamp(view.createdAt) : ''} wide>
	{#if view}
		{#if view.kind === 'video'}
			<video class="cam-player" bind:this={player} src={view.url} controls autoplay playsinline onloadedmetadata={seek}><track kind="captions" /></video>
		{:else}
			<img class="cam-player" src={view.url} alt="" />
		{/if}
		<div class="row" style="flex-wrap:wrap">
			{#if view.id}
				<button class="ib" onclick={() => step(-1)} aria-label={t('cam.newer')} title={t('cam.newer')}><Icon name="back" size={16} /></button>
				<button class="ib" onclick={() => step(1)} aria-label={t('cam.older')} title={t('cam.older')}><Icon name="chev" size={16} /></button>
			{/if}
			<a class="btn s" href={`${view.url}?download=1`} download><Icon name="download" size={14} />{t('a.download')}</a>
			{#if view.id && admin}
				<button class="btn s" class:on={view.keep} aria-pressed={!!view.keep} onclick={() => keep(view, !view.keep)}><Icon name="lock" size={14} />{view.keep ? t('cam.unkeep') : t('cam.keep')}</button>
				<button class="btn s danger" onclick={() => drop(view)}><Icon name="trash" size={14} />{sure === `m${view.id}` ? t('a.confirm_delete') : t('a.delete')}</button>
			{/if}
		</div>
	{/if}
</Modal>

<Modal bind:this={bulk} title={t('cam.delete_title')} icon="trash">
	<p>{bulkWhat === 'picked' ? t('cam.delete_picked_q', { n: picked.length, size: f.bytes(sizeOf) }) : bulkWhat === 'day' ? t('cam.delete_day_q', { day: f.date(`${day}T12:00:00`) }) : t('cam.delete_all_q', { name: d?.name ?? cam?.name ?? '' })}</p>
	{#if bulkWhat !== 'picked'}<p class="dim sm">{t('cam.delete_kept_note')}</p>{/if}
	{#snippet foot()}
		<span style="flex:1"></span>
		<button class="btn" onclick={() => bulk.hide()}>{t('a.cancel')}</button>
		<button class="btn danger" onclick={bulkDelete}>{t('a.delete')}</button>
	{/snippet}
</Modal>

<style>
	.cam-top {
		display: grid;
		gap: 16px;
		grid-template-columns: minmax(0, 1fr) minmax(240px, 320px);
		margin-bottom: 16px;
		align-items: start;
	}
	.cam-view {
		position: relative;
		min-width: 0;
		background: #000;
		border-radius: var(--r);
	}
	.cam-view:fullscreen {
		display: grid;
		align-content: center;
	}
	.cam-aim {
		position: absolute;
		inset: 0;
		z-index: 2;
		border: 0;
		background: transparent;
		cursor: crosshair;
		outline: 2px dashed rgb(255 255 255 / 0.4);
		outline-offset: -6px;
	}
	.cam-off {
		aspect-ratio: 16 / 9;
		display: grid;
		place-content: center;
		padding: 24px;
		color: #ddd;
		--ink-3: #aaa;
		--ink-2: #bbb;
	}
	.cam-bar {
		position: absolute;
		left: 0;
		right: 0;
		bottom: 0;
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 8px;
		background: linear-gradient(transparent, rgb(0 0 0 / 0.55));
		border-radius: 0 0 var(--r) var(--r);
		z-index: 2;
	}
	.cam-q {
		background: rgb(0 0 0 / 0.5);
	}
	.cam-q button {
		color: #fff;
	}
	.cam-ib {
		color: #fff;
		background: rgb(0 0 0 / 0.45);
	}
	.cam-side {
		display: grid;
		gap: 14px;
	}
	.cam-state {
		display: flex;
		gap: 12px;
		align-items: center;
	}
	.cam-state b::first-letter {
		text-transform: uppercase;
	}
	.cam-state div {
		display: grid;
		gap: 2px;
		min-width: 0;
	}
	.cam-kv dd {
		display: grid;
		justify-items: end;
		overflow-wrap: anywhere;
	}
	.cam-days {
		display: flex;
		gap: 6px;
		overflow-x: auto;
		padding-bottom: 6px;
		margin-bottom: 8px;
		scrollbar-width: thin;
		align-items: center;
	}
	.cam-days .chip {
		cursor: pointer;
		height: 28px;
		flex: none;
	}
	.cam-days .chip small {
		opacity: 0.7;
	}
	.cam-date {
		flex: none;
		width: 150px;
		height: 28px;
		padding: 0 8px;
	}
	.cam-tools {
		margin-bottom: 12px;
		flex-wrap: wrap;
		gap: 8px;
	}
	.cam-pickbar {
		position: sticky;
		top: 8px;
		z-index: 4;
		flex-wrap: wrap;
		gap: 8px;
		padding: 10px 12px;
		margin-bottom: 12px;
		border-radius: var(--r);
		background: var(--panel);
		border: 1px solid var(--line);
	}
	.cam-ev {
		gap: 12px;
	}
	.cam-th {
		width: 96px;
		aspect-ratio: 16 / 9;
		flex: none;
		display: grid;
		place-items: center;
		border: 0;
		padding: 0;
		border-radius: 6px;
		overflow: hidden;
		background: color-mix(in oklab, var(--ink) 8%, transparent);
		color: var(--ink-2);
		cursor: pointer;
	}
	.cam-th:disabled {
		cursor: default;
	}
	.cam-th img,
	.cam-pic img {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: block;
	}
	.cam-evt {
		flex: 1;
		display: grid;
		gap: 2px;
		min-width: 0;
	}
	.cam-media {
		display: grid;
		gap: 12px;
		grid-template-columns: repeat(auto-fill, minmax(min(200px, 100%), 1fr));
	}
	.cam-m {
		display: grid;
		gap: 6px;
		padding: 0;
		border: 0;
		background: none;
		color: inherit;
		text-align: left;
		cursor: pointer;
		min-width: 0;
	}
	.cam-pic {
		position: relative;
		display: block;
		aspect-ratio: 16 / 9;
		border-radius: 8px;
		overflow: hidden;
		outline: 2px solid transparent;
		outline-offset: 2px;
	}
	.cam-m.sel .cam-pic {
		outline-color: var(--amber);
	}
	.cam-vid {
		display: grid;
		place-items: center;
		height: 100%;
		background: color-mix(in oklab, var(--ink) 12%, transparent) center / cover no-repeat;
		color: #fff;
	}
	.cam-vid i {
		display: grid;
		place-items: center;
		width: 40px;
		height: 40px;
		border-radius: 50%;
		background: rgb(0 0 0 / 0.55);
	}
	.cam-ck,
	.cam-keep {
		position: absolute;
		top: 6px;
		display: grid;
		place-items: center;
		width: 22px;
		height: 22px;
		border-radius: 50%;
		background: rgb(0 0 0 / 0.55);
		color: transparent;
		border: 1.5px solid #fff;
	}
	.cam-ck {
		left: 6px;
	}
	.cam-m.sel .cam-ck {
		background: var(--amber);
		color: #000;
		border-color: var(--amber);
	}
	.cam-keep {
		right: 6px;
		color: #fff;
		border: 0;
	}
	.cam-cont {
		position: absolute;
		left: 6px;
		bottom: 6px;
		font: 500 10px var(--f-m);
		padding: 2px 6px;
		border-radius: 4px;
		background: rgb(0 0 0 / 0.55);
		color: #fff;
	}
	.cam-m small {
		display: flex;
		justify-content: space-between;
		gap: 8px;
		font-size: 12px;
	}
	.cam-player {
		width: 100%;
		max-height: 70vh;
		background: #000;
		border-radius: 8px;
		display: block;
	}
	@media (max-width: 860px) {
		.cam-top {
			grid-template-columns: minmax(0, 1fr);
		}
	}
	@media (max-width: 560px) {
		.cam-ev .hm {
			display: none;
		}
	}
</style>
