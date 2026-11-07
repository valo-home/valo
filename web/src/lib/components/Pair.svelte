<script>
	import { onDestroy } from 'svelte';
	import { useApp } from '#lib/app.svelte.js';
	import Icon from './Icon.svelte';
	import Hint from './Hint.svelte';
	import Modal from './Modal.svelte';

	const app = useApp();
	const { s, t, f } = app;
	let m = $state();
	let tab = $state('zigbee');
	let until = $state(0);
	let now = $state(Date.now());
	let steps = $state([]);
	let via = $state('');
	let acc = $state(null);
	let devId = $state('');
	let closing = $state(false);
	let stops = [];
	let target = $state(null);
	const placed = new Set();

	async function place(ieee) {
		if (!target || !ieee || placed.has(ieee)) return;
		placed.add(ieee);
		for (let i = 0; i < 20 && !s.devices[ieee]; i++) await new Promise((r) => setTimeout(r, 500));
		if (!s.devices[ieee] || s.devices[ieee].roomId) return;
		const r = await app.run(() => app.api('PATCH', `/devices/${encodeURIComponent(ieee)}`, { roomId: target.id }));
		if (r) app.toast(t('pair.placed', { name: r.name, room: target.name }));
	}

	export function show(room = null) {
		stop();
		target = room;
		placed.clear();
		tab = 'zigbee';
		acc = null;
		closing = false;
		steps = [];
		m.show();
		stops.push(app.sub(['zigbee']), app.on('zigbee', (d) => {
				if (d?.type !== 'pairing') return;
				steps = [{ ...d, at: Date.now() }, ...steps].slice(0, 12);
				if (d.data?.status === 'successful') place(d.data.ieee_address);
			}));
		const i = setInterval(() => (now = Date.now()), 1000);
		stops.push(() => clearInterval(i));
		app.api('GET', '/zigbee').then((z) => (until = z.permitJoin && z.permitJoinEnd ? z.permitJoinEnd : 0)).catch(() => {});
	}
	const stop = () => (stops.forEach((fn) => fn()), (stops = []));
	onDestroy(stop);
	const left = $derived(Math.max(0, Math.round((until - now) / 1000)));
	const routers = $derived(Object.values(s.devices).filter((d) => d.source === 'zigbee' && d.attrs.type === 'Router' && d.available));

	async function join(time) {
		const r = await app.run(() => app.api('POST', '/zigbee/permit-join', { time, via: via || null }));
		if (r) until = time ? r.until * 1000 : 0;
	}
	async function account() {
		acc = await app.run(() => app.api('POST', '/mqtt/accounts', { deviceId: devId.trim() }));
	}
	const label = (st) => t(`pair.${st.event}${st.data?.status ? `_${st.data.status}` : ''}`);
</script>

<Modal bind:this={m} title={t('pair.title')} wide onclose={stop}>
	<div class="seg">
		<button class:on={tab === 'zigbee'} aria-pressed={!!(tab === 'zigbee')} onclick={() => (tab = 'zigbee')}>Zigbee</button>
		<button class:on={tab === 'mqtt'} aria-pressed={!!(tab === 'mqtt')} onclick={() => (tab = 'mqtt')}>{t('pair.mqtt')}</button>
	</div>
	{#if tab === 'zigbee'}
		<p class="dim" style="margin:0">{t('pair.zigbee_hint')} <Hint k="zb_pair" doc="zigbee" /></p>
		{#if target}<p class="sm" style="margin:0"><Icon name="rooms" size={14} /> {t('pair.into_room', { room: target.name })}</p>{/if}
		<div class="row">
			<label class="f" style="flex:1">{t('pair.via')}
				<select class="in" bind:value={via}>
					<option value="">{t('pair.via_all')}</option>
					{#each routers as d (d.id)}<option value={d.id}>{d.name}</option>{/each}
				</select>
			</label>
		</div>
		<div class="row">
			{#if left}
				<span class="chip amber"><i class="dot" style="background:var(--amber)"></i>{t('pair.open_for', { n: left })}</span>
				<span class="sp"></span>
				<button class="btn ghost s" onclick={() => (closing ? ((closing = false), join(0)) : (closing = true))}>{closing ? t('pair.stop_confirm') : t('pair.stop')}</button>
				<button class="btn pri" onclick={() => ((closing = false), join(254))}><Icon name="zig" size={16} />{t('pair.extend')}</button>
			{:else}
				<button class="btn pri" onclick={() => join(254)}><Icon name="zig" size={16} />{t('pair.start')}</button>
			{/if}
		</div>
		<div class="steps">
			{#each steps as st (st.at)}
				<div class="step" class:ok={st.data?.status === 'successful' || st.event === 'device_joined'}>
					<i></i>{label(st)} <span class="mono sm">{st.data?.friendly_name || st.data?.ieee_address}</span>
					{#if st.data?.status === 'successful'}<a class="sm" href={app.path(`/devices/${st.data.ieee_address}`)} onclick={() => m.hide()}>{t('pair.configure')}</a>{/if}
					<em>{f.sec(st.at)}</em>
				</div>
			{:else}
				{#if left}<div class="step run"><i></i>{t('pair.waiting')}</div>{/if}
			{/each}
		</div>
	{:else}
		<p class="dim" style="margin:0">{t('pair.mqtt_hint')}</p>
		<div class="row">
			<input class="in" style="flex:1" placeholder="sauna-ctrl" bind:value={devId} aria-label={t('pair.device_id')} />
			<button class="btn pri" disabled={!devId.trim()} onclick={account}><Icon name="key" size={16} />{t('pair.issue')}</button>
		</div>
		{#if acc}
			<dl class="kv">
				<dt>{t('pair.user')}</dt><dd class="mono">{acc.username}</dd>
				<dt>{t('pair.password')}</dt><dd class="mono">{acc.password}</dd>
				<dt>{t('pair.base')}</dt><dd class="mono">{acc.base}</dd>
			</dl>
			<pre class="code">{acc.base}/meta  {'{"name":"...","caps":[{"id":"t","type":"num","unit":"°C"}]}'}
{acc.base}/state {'{"t":21.5}'}
{acc.base}/avail online
{acc.base}/set   {'{"cmd":"...","values":{...}}'}</pre>
			<p class="sm dim" style="margin:0">{t('pair.once')}</p>
		{/if}
	{/if}
</Modal>
