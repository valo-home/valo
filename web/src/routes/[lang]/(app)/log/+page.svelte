<script>
	import { useApp } from '#lib/app.svelte.js';
	import { actor, evText, levelIcon } from '#lib/events.js';
	import Icon from '#lib/components/Icon.svelte';
	import Hint from '#lib/components/Hint.svelte';
	import Modal from '#lib/components/Modal.svelte';

	const app = useApp();
	const { s, t, f } = app;
	const KINDS = ['device', 'command', 'scene', 'flow', 'room', 'camera', 'media', 'zigbee', 'ext', 'mqtt', 'user', 'token', 'ai', 'backup', 'home'];
	let kind = $state('');
	let level = $state('');
	let q = $state('');
	let list = $state([]);
	let more = $state(true);
	let chain = $state([]);
	let m = $state();
	let tm;

	async function load(reset = true) {
		const before = reset ? '' : `&before=${list.at(-1)?.id ?? ''}`;
		const rows = await app.api('GET', `/events?limit=60&kind=${kind}&level=${level}&q=${encodeURIComponent(q)}${before}`).catch(() => []);
		list = reset ? rows : [...list, ...rows];
		more = rows.length === 60;
	}
	$effect(() => {
		[kind, level];
		clearTimeout(tm);
		tm = setTimeout(load, q ? 300 : 0);
	});
	$effect(() =>
		app.on('event', (e) => {
			if ((!kind || e.type.startsWith(`${kind}.`)) && (!level || e.level === level) && !q) list = [e, ...list.filter((x) => x.id !== e.id)];
		})
	);
	async function open(e) {
		chain = await app.api('GET', `/events/${e.id}/chain`).catch(() => [e]);
		m.show();
	}
</script>

<svelte:head><title>{t('nav.log')} · valo</title></svelte:head>

<div class="ph"><div><h1>{t('nav.log')} <Hint k="p_log" doc="log" /></h1><p>{t('log.sub')}</p></div></div>
<div class="row" style="margin-bottom:14px">
	<input class="in" style="max-width:260px" placeholder={t('a.search')} aria-label={t('a.search')} bind:value={q} oninput={() => (clearTimeout(tm), (tm = setTimeout(load, 300)))} />
	<select class="in" style="max-width:200px" bind:value={kind} aria-label={t('log.kind')}><option value="">{t('log.all_kinds')}</option>{#each KINDS as k}<option value={k}>{t(`lk.${k}`)}</option>{/each}</select>
	<div class="seg">{#each ['', 'info', 'ok', 'warn', 'crit'] as l}<button class:on={level === l} aria-pressed={!!(level === l)} onclick={() => (level = l)}>{t(l ? `lvl.${l}` : 'log.all_levels')}</button>{/each}</div>
</div>
<section class="card">
	{#each list as e (e.id)}
		<div class="ev lg {e.level}">
			<time>{f.stamp(e.ts)}</time>
			<div><button class="dn" style="white-space:normal" onclick={() => open(e)}><b>{evText(app, e)}</b></button><span class="why">{actor(app, e.actor)}{#if e.causeId} · {t('log.has_cause')}{/if}</span></div>
			<span class="chip {e.level === 'info' ? '' : e.level}">{t(`lk.${e.type.split('.')[0]}`)}</span>
		</div>
	{:else}<p class="dim">{t('log.empty')}</p>{/each}
	{#if more && list.length}<div style="text-align:center;margin-top:12px"><button class="btn" onclick={() => load(false)}>{t('log.more')}</button></div>{/if}
</section>

<Modal bind:this={m} kind="drawer" icon="link" title={t('log.chain')} sub={t('log.chain_hint')}>
	<div class="steps">
		{#each chain as e, i (e.id)}
			<div class="drow" style="grid-template-columns:32px minmax(0,1fr)">
				<div class="dico" style="color:var(--{e.level === 'info' ? 'frost' : e.level})"><Icon name={levelIcon(e.level)} size={16} /></div>
				<div><b style="font-weight:500">{evText(app, e)}</b><div class="ds">{f.stamp(e.ts)} · {actor(app, e.actor)}</div>
					{#if e.deviceId && s.devices[e.deviceId]}<a class="sm" href={app.path(`/devices/${e.deviceId}`)} onclick={() => m.hide()}>{s.devices[e.deviceId].name}</a>{/if}
					{#if e.flowId}<a class="sm" href={app.path(`/flows/${e.flowId}`)} onclick={() => m.hide()}>{s.flows.find((x) => x.id === e.flowId)?.name ?? e.flowId}</a>{/if}
				</div>
			</div>
			{#if i < chain.length - 1}<div class="dim sm" style="padding-left:12px">↓</div>{/if}
		{/each}
	</div>
</Modal>
