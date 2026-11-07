<script>
	import { useApp } from '#lib/app.svelte.js';
	import Icon from './Icon.svelte';

	let { cam, actions = true, onchanged } = $props();
	const app = useApp();
	const { t, f } = app;
	const code = $derived(cam?.status?.code || 'ok');
	const bad = $derived(!['ok', 'starting'].includes(code));
	const has = (x) => cam?.features?.includes(x);
	let busy = $state('');
	let sure = $state(false);

	const TONE = { ok: 'ok', starting: 'amber', no_video: 'warn', driver_stopped: 'warn' };
	async function act(name) {
		if (name === 'reboot' && !sure) return void (sure = true);
		sure = false;
		busy = name;
		const r = await app.run(() => app.api('POST', `/cameras/${encodeURIComponent(cam.id)}/action`, { action: name }), t(`cam.done_${name}`));
		busy = '';
		if (r) onchanged?.();
	}
	async function find() {
		busy = 'discover';
		const r = await app.run(() => app.api('POST', `/cameras/${encodeURIComponent(cam.id)}/discover`));
		busy = '';
		if (!r) return;
		if (r.moved) app.toast(t('cam.found_moved', { host: r.match }));
		else if (r.match) app.toast(t('cam.found_same', { host: r.match }));
		else app.toast(t('cam.found_none', { n: r.found.length }), 'warn');
		onchanged?.();
	}
</script>

<div class="cst {TONE[code] || 'crit'}" role="status">
	<span class="cst-i"><Icon name={code === 'ok' ? 'check' : code === 'starting' ? 'refresh' : code === 'no_video' ? 'camera' : 'warn'} size={18} /></span>
	<div class="cst-t">
		<b>{t(`cam.st_${code}`)}</b>
		<small class="dim">
			{#if cam?.status?.since && code !== 'ok'}{t('cam.st_since', { at: f.ago(cam.status.since) })}{/if}
			{#if bad}{' '}{t(`cam.sth_${code}`)}{/if}
		</small>
		{#if bad && cam?.status?.detail}<small class="mono cst-d">{cam.status.detail}</small>{/if}
	</div>
</div>
{#if actions && bad && app.can('admin')}
	<div class="row cst-a">
		<button class="btn s" onclick={() => act('reconnect')} disabled={!!busy}><Icon name="refresh" size={14} />{t('cam.a_reconnect')}</button>
		{#if has('discover') && ['offline', 'other_device'].includes(code)}<button class="btn s" onclick={find} disabled={!!busy}><Icon name="search" size={14} />{busy === 'discover' ? t('cam.searching') : t('cam.a_discover')}</button>{/if}
		{#if has('actions') && code === 'no_video'}<button class="btn s" onclick={() => act('restart_stream')} disabled={!!busy}><Icon name="play" size={14} />{t('cam.a_restart_stream')}</button>{/if}
		{#if has('actions') && !['offline', 'other_device', 'driver_stopped'].includes(code)}<button class="btn s" class:danger={sure} onclick={() => act('reboot')} disabled={!!busy}><Icon name="power" size={14} />{sure ? t('cam.a_reboot_sure') : t('cam.a_reboot')}</button>{/if}
		<a class="btn s" href={app.path(`/cameras/${encodeURIComponent(cam.id)}/settings?tab=service`)}><Icon name="shield" size={14} />{t('cam.a_diagnose')}</a>
	</div>
{/if}

<style>
	.cst {
		display: flex;
		gap: 12px;
		align-items: flex-start;
	}
	.cst-i {
		flex: none;
		display: grid;
		place-items: center;
		width: 34px;
		height: 34px;
		border-radius: 50%;
		color: var(--tone);
		background: color-mix(in oklab, var(--tone) 14%, transparent);
	}
	.cst.ok {
		--tone: var(--ok);
	}
	.cst.amber {
		--tone: var(--amber-ink);
	}
	.cst.warn {
		--tone: var(--warn);
	}
	.cst.crit {
		--tone: var(--crit);
	}
	.cst-t {
		display: grid;
		gap: 2px;
		min-width: 0;
	}
	.cst-t b {
		color: var(--tone);
	}
	.cst-d {
		font-size: 11px;
		color: var(--ink-3);
		overflow-wrap: anywhere;
	}
	.cst-a {
		flex-wrap: wrap;
		gap: 8px;
		margin-top: 10px;
	}
</style>
