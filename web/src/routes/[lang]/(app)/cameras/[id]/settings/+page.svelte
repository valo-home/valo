<script>
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { useApp } from '#lib/app.svelte.js';
	import CameraStatus from '#lib/components/CameraStatus.svelte';
	import CameraVision from '#lib/components/CameraVision.svelte';
	import DriverFields from '#lib/components/DriverFields.svelte';
	import Hint from '#lib/components/Hint.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import Toggle from '#lib/components/Toggle.svelte';

	const app = useApp();
	const { s, t, f } = app;
	const tx = (x) => (x && typeof x === 'object' ? (x[app.lang] ?? x.en ?? Object.values(x)[0]) : (x ?? ''));
	const id = $derived(page.params.id);
	const enc = $derived(encodeURIComponent(page.params.id));
	const admin = $derived(app.can('admin'));
	const LABELS = ['motion', 'person', 'car', 'animal'];
	const SECTIONS = ['motion', 'daynight', 'privacy', 'image', 'audio', 'streams', 'time', 'other'];

	let cam = $state(null);
	let drivers = $state([]);
	let missing = $state(false);
	let tab = $state(page.url.searchParams.get('tab') || 'general');
	let gen = $state({ name: '', roomId: '', sort: 0 });
	let conn = $state({});
	let tested = $state(null);
	let rec = $state(null);
	let fields = $state([]);
	let vals = $state({});
	let failed = $state({});
	let fieldsErr = $state('');
	let fieldsBusy = $state(false);
	let diag = $state(null);
	let found = $state(null);
	let storage = $state(null);
	let busy = $state('');
	let sure = $state('');
	let keepMedia = $state(true);
	let preset = $state('');

	const has = (x) => cam?.features?.includes(x);
	const d = $derived(cam ? s.devices[cam.deviceId] : null);
	const drv = $derived(drivers.find((x) => x.id === cam?.driver));
	const tabs = $derived(
		cam
			? [
					['general', 'cam.t_general', 'sliders'],
					['connection', 'cam.t_connection', 'link'],
					['record', 'cam.t_record', 'record'],
					...(has('settings') ? [['camera', 'cam.t_camera', 'camera']] : []),
					['vision', 'cam.t_vision', 'spark'],
					...(cam.ptz && has('ptz') ? [['ptz', 'cam.t_ptz', 'layers']] : []),
					['service', 'cam.t_service', 'shield'],
					['remove', 'cam.t_remove', 'trash']
				]
			: []
	);
	const grouped = $derived(SECTIONS.map((sec) => [sec, fields.filter((x) => (SECTIONS.includes(x.section) ? x.section : 'other') === sec)]).filter(([, xs]) => xs.length));
	const changed = $derived(fields.filter((x) => x.type !== 'info' && !x.readonly && vals[x.key] !== x.value).map((x) => x.key));
	const kbps = $derived(cam?.video?.kbps || fields.find((x) => x.key === (rec?.stream === 'sub' ? 'sub_bitrate' : 'main_bitrate'))?.value || 0);
	const perDay = $derived(kbps ? (kbps * 1000 * 86400) / 8 : 0);
	const fieldName = (fd) => (t.has(`cs.${fd.key}`) ? t(`cs.${fd.key}`) : tx(fd.name) || fd.key);
	const optName = (fd, o) => (t.has(`cs.${fd.key}_${o}`) ? t(`cs.${fd.key}_${o}`) : o);
	const unit = (u) => (u ? (t.has(`u.${u}`) ? t(`u.${u}`) : u) : '');

	async function load() {
		try {
			const [c, dr] = await Promise.all([app.api('GET', `/cameras/${enc}`), app.api('GET', '/cameras/drivers')]);
			cam = c;
			drivers = dr;
			missing = false;
		} catch (e) {
			missing = true;
			console.warn('camera load failed', id, e?.message);
			return;
		}
		gen = { name: d?.name ?? cam.name, roomId: d?.roomId ?? cam.roomId ?? '', sort: cam.sort };
		rec = structuredClone($state.snapshot(cam.record));
		resetConn();
	}
	function resetConn() {
		conn = Object.fromEntries((drv?.fields || []).map((fd) => [fd.key, fd.type === 'secret' ? '' : (cam.config[fd.key] ?? fd.default ?? '')]));
		tested = null;
	}
	async function refresh() {
		cam = await app.api('GET', `/cameras/${enc}`).catch((e) => (console.warn('camera reload failed', e?.message), cam));
	}
	async function loadFields() {
		fieldsBusy = true;
		fieldsErr = '';
		try {
			const r = await app.api('GET', `/cameras/${enc}/settings`);
			fields = r.fields;
			vals = Object.fromEntries(r.fields.map((x) => [x.key, x.value]));
			failed = {};
		} catch (e) {
			fieldsErr = e.message;
			console.warn('camera settings load failed', id, e?.message);
		} finally {
			fieldsBusy = false;
		}
	}
	$effect(() => {
		id;
		cam = null;
		load();
	});
	let shown = '';
	$effect(() => {
		const k = `${tab}:${cam?.id ?? ''}`;
		if (!cam || k === shown) return;
		shown = k;
		const u = new URL(page.url);
		u.searchParams.set('tab', tab);
		history.replaceState(history.state, '', u);
		if (tab === 'camera' && has('settings')) loadFields();
		if (tab === 'record' && !storage) app.api('GET', '/media/storage').then((r) => (storage = r)).catch((e) => console.warn('storage load failed', e?.message));
	});

	async function saveGeneral() {
		busy = 'general';
		const r = await app.run(() => app.api('PATCH', `/cameras/${enc}`, { name: gen.name, roomId: gen.roomId || null, sort: Number(gen.sort) || 0 }), t('cam.saved'));
		busy = '';
		if (r?.id) cam = r;
	}
	function connChanged() {
		return Object.entries(conn).some(([k, v]) => {
			const fd = drv?.fields.find((x) => x.key === k);
			return fd?.type === 'secret' ? v !== '' : String(v ?? '') !== String(cam.config[k] ?? fd?.default ?? '');
		});
	}
	async function test() {
		busy = 'test';
		tested = null;
		try {
			tested = { ok: true, ...(await app.api('POST', `/cameras/${enc}/test`, { config: $state.snapshot(conn) })) };
		} catch (e) {
			tested = { ok: false, error: e.message };
		} finally {
			busy = '';
		}
	}
	async function saveConn() {
		busy = 'conn';
		const r = await app.run(() => app.api('PATCH', `/cameras/${enc}`, { config: $state.snapshot(conn) }), t('cam.saved'));
		busy = '';
		if (r?.id) {
			cam = r;
			resetConn();
		}
	}
	async function saveRecord() {
		busy = 'record';
		const r = await app.run(() => app.api('PATCH', `/cameras/${enc}`, { record: $state.snapshot(rec) }), t('cam.saved'));
		busy = '';
		if (r?.id) {
			cam = r;
			rec = structuredClone($state.snapshot(r.record));
		}
	}
	function toggleLabel(l) {
		const cur = rec.labels.length ? rec.labels : [...LABELS];
		const next = cur.includes(l) ? cur.filter((x) => x !== l) : [...cur, l];
		rec.labels = LABELS.every((x) => next.includes(x)) ? [] : next;
	}
	async function saveFields() {
		busy = 'fields';
		const values = Object.fromEntries(changed.map((k) => [k, $state.snapshot(vals[k])]));
		try {
			const r = await app.api('PATCH', `/cameras/${enc}/settings`, { values });
			fields = r.fields;
			failed = r.failed;
			vals = Object.fromEntries(r.fields.map((x) => [x.key, x.value]));
			if (Object.keys(r.failed).length) app.toast(t('cam.set_partly'), 'warn');
			else app.toast(t('cam.saved'));
		} catch (e) {
			app.toast(e.message, 'crit');
		} finally {
			busy = '';
		}
	}
	async function action(name) {
		if (['reboot', 'calibrate'].includes(name) && sure !== name) return void (sure = name);
		sure = '';
		busy = name;
		const r = await app.run(() => app.api('POST', `/cameras/${enc}/action`, { action: name }), t(`cam.done_${name}`));
		busy = '';
		if (r?.detail) app.toast(`${t(`cam.done_${name}`)}: ${r.detail}`);
		await refresh();
		if (name === 'sync_time' && tab === 'camera') loadFields();
	}
	async function diagnose() {
		busy = 'diag';
		diag = await app.api('GET', `/cameras/${enc}/diagnose`).catch((e) => (app.toast(e.message, 'crit'), diag));
		busy = '';
		await refresh();
	}
	async function discover() {
		busy = 'discover';
		found = await app.api('POST', `/cameras/${enc}/discover`).catch((e) => (app.toast(e.message, 'crit'), null));
		busy = '';
		if (found?.moved) {
			app.toast(t('cam.found_moved', { host: found.match }));
			await load();
		}
	}
	async function addPreset() {
		busy = 'preset';
		const r = await app.run(() => app.api('POST', `/cameras/${enc}/presets`, { name: preset }), t('cam.saved'));
		busy = '';
		if (Array.isArray(r)) {
			cam.presets = r;
			preset = '';
		}
	}
	async function renamePreset(p) {
		const r = await app.run(() => app.api('PATCH', `/cameras/${enc}/presets/${encodeURIComponent(p.id)}`, { name: p.name }), t('cam.saved'));
		if (Array.isArray(r)) cam.presets = r;
	}
	async function dropPreset(p) {
		if (sure !== `p${p.id}`) return void (sure = `p${p.id}`);
		sure = '';
		const r = await app.run(() => app.api('DELETE', `/cameras/${enc}/presets/${encodeURIComponent(p.id)}`));
		if (Array.isArray(r)) cam.presets = r;
	}
	async function ptz(body) {
		await app.run(() => app.api('POST', `/cameras/${enc}/ptz`, body), body.op === 'calibrate' ? t('cam.done_calibrate') : '');
	}
	async function remove() {
		if (sure !== 'remove') return void (sure = 'remove');
		if (await app.run(() => app.api('DELETE', `/cameras/${enc}?media=${keepMedia ? 'keep' : 'delete'}`), t('cam.removed'))) goto(app.path('/cameras'));
	}
	const val = (c) => {
		if (c.value == null || c.value === '') return '';
		if (c.key === 'uptime') return t('cam.uptime', { h: Math.floor(c.value / 3600), m: Math.floor((c.value % 3600) / 60) });
		if (c.key === 'memory') return `${f.n(c.value, 1)} ${t('u.mb')}`;
		if (['clock', 'buffer', 'continuous'].includes(c.key)) return `${f.n(c.value, 0)} ${t('u.s')}`;
		if (c.key === 'video_stream') return `${f.n(c.value, 0)} ${t('u.kbps')}`;
		return String(c.value);
	};
	const webUi = $derived(cam?.config?.host ? `http://${String(cam.config.host).replace(/^[a-z]+:\/\//, '')}/` : '');
</script>

<svelte:head><title>{t('cam.settings')} · {d?.name ?? cam?.name ?? t('nav.cameras')} · valo</title></svelte:head>

{#if missing}
	<div class="empty">{t('cam.missing')} <a href={app.path('/cameras')}>{t('nav.cameras')}</a></div>
{:else if cam && rec}
	<div class="ph">
		<div>
			<div class="crumbs"><a href={app.path('/cameras')}>{t('nav.cameras')}</a> / <a href={app.path(`/cameras/${enc}`)}>{d?.name ?? cam.name}</a></div>
			<h1>{t('cam.settings')} <Hint k="cam_settings" doc="cameras" /></h1>
			<p class="meta"><span>{tx(cam.driverName)}</span>{#if cam.info.model}<span>{cam.info.model}</span>{/if}</p>
		</div>
		<a class="btn" href={app.path(`/cameras/${enc}`)}><Icon name="play" size={16} />{t('cam.to_live')}</a>
	</div>
	<div class="card cs-status"><CameraStatus {cam} onchanged={refresh} /></div>
	<div class="sub">
		<nav class="subn" aria-label={t('cam.settings')}>
			{#each tabs as [k, l, ic]}<button class:on={tab === k} aria-pressed={tab === k} onclick={() => ((tab = k), (sure = ''))}><Icon name={ic} size={15} />{t(l)}</button>{/each}
		</nav>
		<div class="g" style="align-content:start">
			{#if tab === 'general'}
				<section class="card g" style="gap:14px">
					<div class="fg">
						<label class="f"><span>{t('devs.name')}</span><input class="in" bind:value={gen.name} disabled={!admin} /></label>
						<label class="f">
							<span>{t('devs.room')}</span>
							<select class="in" bind:value={gen.roomId} disabled={!admin}><option value="">{t('devs.no_room')}</option>{#each s.rooms as r (r.id)}<option value={r.id}>{r.name}</option>{/each}</select>
						</label>
						<label class="f"><span>{t('cam.sort')}</span><input class="in" type="number" min="0" max="999" bind:value={gen.sort} disabled={!admin} /></label>
					</div>
					<small class="dim">{t('cam.sort_hint')}</small>
					{#if admin}<div><button class="btn pri" onclick={saveGeneral} disabled={busy === 'general' || !gen.name.trim()}>{t('a.save')}</button></div>{/if}
				</section>
			{:else if tab === 'connection'}
				<section class="card g" style="gap:14px">
					{#if drv}
						<DriverFields fields={drv.fields} bind:values={conn} secrets={cam.secrets} />
						<small class="dim">{t('cam.secret_keep')}</small>
						{#if tested}
							<div class="cs-test" class:bad={!tested.ok}>
								<Icon name={tested.ok ? 'check' : 'warn'} size={16} />
								{#if tested.ok}<span>{t('cam.test_ok', { streams: tested.streams.map((x) => (x === 'main' ? 'HD' : 'SD')).join(', ') })}{#if tested.info?.model}{' · '}{tested.info.model}{/if}</span>{:else}<span>{tested.error}</span>{/if}
							</div>
						{/if}
						{#if admin}
							<div class="row">
								<button class="btn" onclick={test} disabled={!!busy}><Icon name="refresh" size={14} />{busy === 'test' ? t('cam.checking') : t('cam.test')}</button>
								<button class="btn pri" onclick={saveConn} disabled={!!busy || !connChanged()}>{busy === 'conn' ? t('cam.checking') : t('a.save')}</button>
								{#if connChanged()}<button class="btn" onclick={resetConn}>{t('a.cancel')}</button>{/if}
							</div>
						{/if}
					{:else}
						<p class="dim sm">{t('cam.driver_missing', { id: cam.driver })}</p>
					{/if}
				</section>
			{:else if tab === 'record'}
				<section class="card g" style="gap:16px">
					<h3><Icon name="record" size={16} />{t('cam.recording')} <Hint k="cam_record" doc="cameras" /></h3>
					<div class="seg" role="group" aria-label={t('cam.recording')}>
						{#each [['events', 'cam.mode_events'], ['continuous', 'cam.mode_continuous'], ['off', 'cam.mode_off']] as [k, l]}<button class:on={rec.mode === k} aria-pressed={rec.mode === k} onclick={() => (rec.mode = k)} disabled={!admin}>{t(l)}</button>{/each}
					</div>
					<small class="dim">{t(`cam.mode_${rec.mode}_hint`)}</small>
					{#if rec.mode !== 'off'}
						<div class="cs-nums">
							<label class="f"><span>{t('cam.pre')}</span><input class="in" type="number" min="0" max="30" bind:value={rec.pre} disabled={!admin} /></label>
							<label class="f"><span>{t('cam.post')}</span><input class="in" type="number" min="0" max="30" bind:value={rec.post} disabled={!admin} /></label>
							<label class="f"><span>{t('cam.max')}</span><input class="in" type="number" min="10" max="600" bind:value={rec.max} disabled={!admin} /></label>
						</div>
						<div class="f">
							<span>{t('cam.rec_labels')}</span>
							<div class="cs-chips">
								{#each LABELS as l}
									{@const on = !rec.labels.length || rec.labels.includes(l)}
									<button class="chip" class:amber={on} aria-pressed={on} onclick={() => toggleLabel(l)} disabled={!admin}>{#if on}<Icon name="check" size={12} />{/if}{t(`cam.l_${l}`)}</button>
								{/each}
							</div>
						</div>
						<div class="cs-two">
							<div class="f">
								<span>{t('cam.rec_stream')}</span>
								<div class="seg">
									{#each [['main', 'HD'], ['sub', 'SD']] as [k, l]}<button class:on={rec.stream === k} aria-pressed={rec.stream === k} onclick={() => (rec.stream = k)} disabled={!admin || (k === 'sub' && !cam.streams.includes('sub'))}>{l}</button>{/each}
								</div>
							</div>
							<div class="f">
								<span>{t('cam.rec_audio')}</span>
								<Toggle on={rec.audio} label={t('cam.rec_audio')} disabled={!admin} onclick={() => (rec.audio = !rec.audio)} />
							</div>
						</div>
						<div class="f">
							<span>{t('cam.schedule')}</span>
							<div class="row" style="flex-wrap:wrap">
								<div class="seg">
									{#each [['always', 'cam.sch_always'], ['hours', 'cam.sch_hours']] as [k, l]}<button class:on={rec.schedule.mode === k} aria-pressed={rec.schedule.mode === k} onclick={() => (rec.schedule.mode = k)} disabled={!admin}>{t(l)}</button>{/each}
								</div>
								{#if rec.schedule.mode === 'hours'}
									<label class="row sm">{t('cam.from')}<input class="in cs-time" type="time" bind:value={rec.schedule.from} disabled={!admin} /></label>
									<label class="row sm">{t('cam.to')}<input class="in cs-time" type="time" bind:value={rec.schedule.to} disabled={!admin} /></label>
								{/if}
							</div>
							<small class="dim">{t('cam.schedule_hint')}</small>
						</div>
						{#if rec.mode === 'continuous'}
							<div class="cs-est">
								<label class="f"><span>{t('cam.keep_days')}</span><input class="in" type="number" min="1" max="365" bind:value={rec.keep_days} disabled={!admin} /></label>
								<div class="sm">
									{#if perDay}
										{t('cam.estimate', { day: f.bytes(perDay), total: f.bytes(perDay * (rec.keep_days || 1)), kbps: f.n(kbps, 0) })}
										{#if storage}<br /><span class:warn-t={perDay * (rec.keep_days || 1) > storage.free}>{t('cam.estimate_free', { free: f.bytes(storage.free) })}</span>{/if}
									{:else}<span class="dim">{t('cam.estimate_unknown')}</span>{/if}
								</div>
							</div>
						{/if}
					{/if}
					<label class="f cs-short"><span>{t('cam.offline_min')}</span><input class="in" type="number" min="0" max="1440" bind:value={rec.offline_min} disabled={!admin} /></label>
					<small class="dim">{t('cam.offline_min_hint')}</small>
					{#if admin}<div><button class="btn pri" onclick={saveRecord} disabled={busy === 'record'}>{t('a.save')}</button></div>{/if}
				</section>
			{:else if tab === 'camera'}
				{#if fieldsBusy && !fields.length}
					<p class="dim">{t('w.loading')}</p>
				{:else if fieldsErr}
					<section class="card g"><div class="cs-test bad"><Icon name="warn" size={16} /><span>{fieldsErr}</span></div><div><button class="btn" onclick={loadFields}><Icon name="refresh" size={14} />{t('cam.retry')}</button></div></section>
				{:else}
					{#each grouped as [sec, xs] (sec)}
						<section class="card g" style="gap:12px">
							<h3>{t(`cs_sec.${sec}`)}{#if sec === 'motion'} <Hint k="cam_motion" doc="cameras" />{/if}</h3>
							{#each xs as fd (fd.key)}
								<div class="cs-field" class:bad={failed[fd.key]}>
									<span class="cs-name">{fieldName(fd)}{#if fd.restart}<small class="dim">{t('cam.restarts_stream')}</small>{/if}</span>
									<div class="cs-ctl">
										{#if fd.type === 'bool'}
											<Toggle on={!!vals[fd.key]} label={fieldName(fd)} disabled={!admin || fd.readonly} onclick={() => (vals[fd.key] = !vals[fd.key])} />
										{:else if fd.type === 'int'}
											<input class="cs-range" type="range" min={fd.min} max={fd.max} step={fd.step || 1} bind:value={vals[fd.key]} disabled={!admin || fd.readonly} aria-label={fieldName(fd)} />
											<input class="in cs-num" type="number" min={fd.min} max={fd.max} step={fd.step || 1} bind:value={vals[fd.key]} disabled={!admin || fd.readonly} aria-label={fieldName(fd)} />
											{#if fd.unit}<small class="dim">{unit(fd.unit)}</small>{/if}
										{:else if fd.type === 'select'}
											<div class="seg">{#each fd.options as o}<button class:on={vals[fd.key] === o} aria-pressed={vals[fd.key] === o} onclick={() => (vals[fd.key] = o)} disabled={!admin || fd.readonly}>{optName(fd, o)}</button>{/each}</div>
										{:else}
											<span class="mono sm">{fd.value === '' || fd.value == null ? '-' : fd.unit ? `${fd.value} ${unit(fd.unit)}` : t.has(`cs.${fd.key}_${fd.value}`) ? t(`cs.${fd.key}_${fd.value}`) : fd.value}</span>
										{/if}
									</div>
									{#if failed[fd.key]}<small class="cs-err">{failed[fd.key]}</small>{/if}
								</div>
							{/each}
							{#if sec === 'time' && admin && has('actions')}
								<div class="row" style="flex-wrap:wrap"><button class="btn s" onclick={() => action('sync_time')} disabled={!!busy}><Icon name="clock" size={14} />{t('cam.a_sync_time')}</button><small class="dim">{t('cam.sync_time_hint')}</small></div>
							{/if}
						</section>
					{/each}
					{#if admin}
						<div class="row cs-save">
							<button class="btn pri" onclick={saveFields} disabled={!changed.length || busy === 'fields'}>{busy === 'fields' ? t('cam.checking') : t('cam.apply', { n: changed.length })}</button>
							{#if changed.length}<button class="btn" onclick={() => (vals = Object.fromEntries(fields.map((x) => [x.key, x.value])))}>{t('a.cancel')}</button>{/if}
							<button class="btn" onclick={loadFields} disabled={fieldsBusy}><Icon name="refresh" size={14} />{t('cam.reread')}</button>
						</div>
					{/if}
				{/if}
			{:else if tab === 'vision'}
				<CameraVision camera={cam} {admin} onsaved={(c) => c?.id && (cam = c)} />
			{:else if tab === 'ptz'}
				<section class="card g" style="gap:12px">
					<h3><Icon name="layers" size={16} />{t('cam.presets')} <Hint k="cam_ptz" doc="cameras" /></h3>
					{#each cam.presets as p (p.id)}
						<div class="row cs-preset">
							<input class="in" bind:value={p.name} disabled={!admin} aria-label={t('cam.preset_name')} />
							<button class="btn s" onclick={() => app.run(() => app.api('POST', `/cameras/${enc}/presets/${encodeURIComponent(p.id)}/go`))}><Icon name="play" size={14} />{t('cam.preset_go')}</button>
							{#if admin}
								<button class="btn s" onclick={() => renamePreset(p)}>{t('a.save')}</button>
								<button class="btn s danger" onclick={() => dropPreset(p)}>{sure === `p${p.id}` ? t('a.confirm_delete') : t('a.delete')}</button>
							{/if}
						</div>
					{:else}
						<p class="dim sm">{t('cam.no_presets')}</p>
					{/each}
					{#if admin}
						<div class="row"><input class="in" placeholder={t('cam.preset_name')} bind:value={preset} /><button class="btn" onclick={addPreset} disabled={busy === 'preset'}><Icon name="plus" size={14} />{t('cam.preset_add')}</button></div>
						<small class="dim">{t('cam.preset_hint')}</small>
					{/if}
				</section>
				{#if admin}
					<section class="card g" style="gap:12px">
						<h3><Icon name="refresh" size={16} />{t('cam.calibrate')}</h3>
						<small class="dim">{t('cam.calibrate_hint')}</small>
						<div class="row">
							<button class="btn" onclick={() => ptz({ op: 'home' })}>{t('cam.ptz_home')}</button>
							<button class="btn" class:danger={sure === 'calibrate'} onclick={() => (sure === 'calibrate' ? ((sure = ''), ptz({ op: 'calibrate' })) : (sure = 'calibrate'))}>{sure === 'calibrate' ? t('cam.calibrate_sure') : t('cam.calibrate')}</button>
						</div>
					</section>
				{/if}
			{:else if tab === 'service'}
				<section class="card g" style="gap:12px">
					<h3><Icon name="shield" size={16} />{t('cam.diagnose')} <Hint k="cam_diagnose" doc="cameras" /></h3>
					{#if diag}
						<div class="lst cs-checks">
							{#each diag.checks as c (c.key)}
								<div class="ri">
									<span class="cs-ok" class:yes={c.ok === true} class:no={c.ok === false}><Icon name={c.ok === true ? 'check' : c.ok === false ? 'x' : 'help'} size={14} /></span>
									<span class="cs-cn">{t.has(`cam.dg_${c.key}`) ? t(`cam.dg_${c.key}`) : c.key}</span>
									<span class="mono sm cs-cv">{val(c)}{#if c.detail}<small class="dim">{c.detail}</small>{/if}</span>
								</div>
							{/each}
						</div>
						<small class="dim">{t('cam.checked_at', { at: f.sec(diag.at) })}</small>
					{:else}
						<p class="dim sm">{t('cam.diagnose_hint')}</p>
					{/if}
					{#if admin}<div><button class="btn" onclick={diagnose} disabled={busy === 'diag'}><Icon name="refresh" size={14} />{busy === 'diag' ? t('cam.checking') : t('cam.diagnose_now')}</button></div>{/if}
				</section>
				{#if admin}
					<section class="card g" style="gap:12px">
						<h3><Icon name="power" size={16} />{t('cam.service')}</h3>
						<div class="cs-acts">
							<button class="btn" onclick={() => action('reconnect')} disabled={!!busy}><Icon name="refresh" size={14} />{t('cam.a_reconnect')}</button>
							<small class="dim">{t('cam.a_reconnect_hint')}</small>
							{#if has('actions')}
								<button class="btn" onclick={() => action('restart_stream')} disabled={!!busy}><Icon name="play" size={14} />{t('cam.a_restart_stream')}</button>
								<small class="dim">{t('cam.a_restart_stream_hint')}</small>
								<button class="btn" class:danger={sure === 'reboot'} onclick={() => action('reboot')} disabled={!!busy}><Icon name="power" size={14} />{sure === 'reboot' ? t('cam.a_reboot_sure') : t('cam.a_reboot')}</button>
								<small class="dim">{t('cam.a_reboot_hint')}</small>
							{/if}
							{#if has('discover')}
								<button class="btn" onclick={discover} disabled={!!busy}><Icon name="search" size={14} />{busy === 'discover' ? t('cam.searching') : t('cam.a_discover')}</button>
								<small class="dim">{t('cam.a_discover_hint')}</small>
							{/if}
						</div>
						{#if found}
							<div class="lst">
								{#each found.found as x (x.host)}
									<div class="ri"><span class="mono">{x.host}</span><span class="dim sm" style="flex:1">{x.hostname || x.model}</span>{#if x.same}<span class="chip ok">{t('cam.found_this')}</span>{/if}</div>
								{:else}
									<p class="dim sm">{t('cam.found_none', { n: 0 })}</p>
								{/each}
							</div>
						{/if}
					</section>
				{/if}
				<section class="card">
					<h3><Icon name="cpu" size={16} />{t('cam.device_info')}</h3>
					<dl class="kv">
						{#if cam.info.model}<dt>{t('cam.model')}</dt><dd>{cam.info.model}</dd>{/if}
						{#if cam.info.firmware}<dt>{t('cam.firmware')}</dt><dd class="mono sm">{cam.info.firmware}</dd>{/if}
						{#if cam.info.hostname}<dt>{t('cam.host')}</dt><dd>{cam.info.hostname}</dd>{/if}
						{#if cam.config.host}<dt>{t('cam.address')}</dt><dd class="mono">{cam.config.host}</dd>{/if}
						{#if cam.info.mac}<dt>{t('cam.mac')}</dt><dd class="mono">{cam.info.mac}</dd>{/if}
					</dl>
					{#if webUi}<p class="sm" style="margin:12px 0 0"><a href={webUi} target="_blank" rel="noopener noreferrer">{t('cam.web_ui')}</a> <span class="dim">{t('cam.firmware_hint')}</span></p>{/if}
				</section>
			{:else if tab === 'remove'}
				<section class="card g" style="gap:14px">
					<h3><Icon name="trash" size={16} />{t('cam.remove_title')}</h3>
					{#if admin}
						<label class="row sm"><input type="radio" name="keep" checked={keepMedia} onchange={() => (keepMedia = true)} />{t('cam.remove_keep')}</label>
						<label class="row sm"><input type="radio" name="keep" checked={!keepMedia} onchange={() => (keepMedia = false)} />{t('cam.remove_all')}</label>
						<div><button class="btn danger" onclick={remove}>{sure === 'remove' ? t('a.confirm_delete') : t('cam.remove_btn')}</button></div>
					{:else}
						<p class="dim sm">{t('cam.admin_only')}</p>
					{/if}
				</section>
			{/if}
		</div>
	</div>
{:else}
	<p class="dim">{t('w.loading')}</p>
{/if}

<style>
	.cs-status {
		margin-bottom: 16px;
	}
	.subn button {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.cs-nums {
		display: grid;
		gap: 12px;
		grid-template-columns: repeat(auto-fit, minmax(min(120px, 100%), 1fr));
	}
	.cs-two {
		display: flex;
		flex-wrap: wrap;
		gap: 16px 32px;
	}
	.cs-chips {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}
	.cs-chips .chip {
		cursor: pointer;
		height: 28px;
		padding: 0 10px;
	}
	.cs-time {
		width: 120px;
	}
	.cs-short {
		max-width: 260px;
	}
	.cs-est {
		display: grid;
		grid-template-columns: minmax(0, 200px) minmax(0, 1fr);
		gap: 16px;
		align-items: end;
	}
	.warn-t {
		color: var(--warn);
	}
	.cs-test {
		display: flex;
		gap: 8px;
		align-items: flex-start;
		font-size: 13px;
		color: var(--ok);
		overflow-wrap: anywhere;
	}
	.cs-test.bad {
		color: var(--crit);
	}
	.cs-field {
		display: grid;
		grid-template-columns: minmax(0, 220px) minmax(0, 1fr);
		gap: 6px 16px;
		align-items: center;
		padding: 6px 0;
		border-top: 1px solid var(--line);
	}
	.cs-field:first-of-type {
		border-top: 0;
	}
	.cs-name {
		display: grid;
		gap: 2px;
		font-size: 13px;
	}
	.cs-ctl {
		display: flex;
		align-items: center;
		gap: 10px;
		flex-wrap: wrap;
		min-width: 0;
	}
	.cs-range {
		flex: 1;
		min-width: 120px;
		max-width: 320px;
		accent-color: var(--amber);
	}
	.cs-num {
		width: 84px;
	}
	.cs-err {
		grid-column: 1 / -1;
		color: var(--crit);
	}
	.cs-field.bad .cs-name {
		color: var(--crit);
	}
	.cs-save {
		position: sticky;
		bottom: 12px;
		padding: 10px;
		border-radius: var(--r);
		background: var(--panel);
		border: 1px solid var(--line);
		flex-wrap: wrap;
	}
	.cs-preset .in {
		flex: 1;
		min-width: 0;
	}
	.cs-checks .ri {
		gap: 10px;
		align-items: flex-start;
	}
	.cs-ok {
		flex: none;
		display: grid;
		place-items: center;
		width: 22px;
		height: 22px;
		border-radius: 50%;
		color: var(--ink-3);
		background: color-mix(in oklab, var(--ink) 8%, transparent);
	}
	.cs-ok.yes {
		color: var(--ok);
		background: color-mix(in oklab, var(--ok) 14%, transparent);
	}
	.cs-ok.no {
		color: var(--crit);
		background: color-mix(in oklab, var(--crit) 14%, transparent);
	}
	.cs-cn {
		flex: 1;
		min-width: 0;
		font-size: 13px;
	}
	.cs-cv {
		display: grid;
		justify-items: end;
		text-align: right;
		max-width: 55%;
		overflow-wrap: anywhere;
	}
	.cs-acts {
		display: grid;
		grid-template-columns: max-content minmax(0, 1fr);
		gap: 10px 14px;
		align-items: center;
	}
	@media (max-width: 560px) {
		.cs-field,
		.cs-est,
		.cs-acts {
			grid-template-columns: minmax(0, 1fr);
		}
		.cs-acts small {
			margin-bottom: 6px;
		}
		.cs-cv {
			max-width: 50%;
		}
	}
</style>
