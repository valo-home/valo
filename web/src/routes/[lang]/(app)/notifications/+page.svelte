<script>
	import { useApp } from '#lib/app.svelte.js';
	import { notifText, routeName } from '#lib/events.js';
	import Icon from '#lib/components/Icon.svelte';
	import Hint from '#lib/components/Hint.svelte';
	import Pages from '#lib/components/Pages.svelte';

	const app = useApp();
	const { s, t, f } = app;
	const SIZE = 25;
	let view = $state('active');
	let hist = $state([]);
	let pg = $state(0);
	const order = { crit: 0, warn: 1, ok: 2, info: 3 };
	const list = $derived(view === 'active' ? [...s.notifs].sort((a, b) => order[a.level] - order[b.level] || b.createdAt.localeCompare(a.createdAt)) : hist);
	const load = () => app.api('GET', '/notifications?history=true').then((x) => (hist = x || [])).catch((e) => console.warn('notifications history failed', e));
	$effect(() => {
		view;
		pg = 0;
		if (view === 'all') load();
	});
	$effect(() => {
		const off = [app.on('notif', () => view === 'all' && load()), app.on('notif_gone', () => view === 'all' && load())];
		return () => off.forEach((x) => x());
	});
	const dismiss = (n) => app.run(() => app.api('POST', `/notifications/${n.id}/dismiss`));
</script>

<svelte:head><title>{t('nt.title')} · valo</title></svelte:head>

<div class="ph"><div><h1>{t('nt.title')} <Hint k="p_notifications" doc="log" /></h1><p>{t('nt.sub')}</p></div></div>
<div class="row" style="margin-bottom:14px">
	<div class="seg">
		<button class:on={view === 'active'} aria-pressed={view === 'active'} onclick={() => (view = 'active')}>{t('nt.active')} {s.notifs.length}</button>
		<button class:on={view === 'all'} aria-pressed={view === 'all'} onclick={() => (view = 'all')}>{t('nt.history')}</button>
	</div>
</div>
<section class="card">
	{#each list.slice(pg * SIZE, (pg + 1) * SIZE) as n (n.id)}
		<div class="ev lg {n.level}">
			<time>{f.stamp(n.createdAt)}</time>
			<div style="min-width:0">
				<a class="dn" style="white-space:normal;overflow-wrap:anywhere" href={app.path(`/notifications/${n.id}`)}><b>{notifText(app, n)}</b></a>
				<span class="why">{routeName(app, n.route)} · {n.dismissedAt ? t('nt.closed', { time: f.ago(n.dismissedAt) }) : t('nt.open_now')}</span>
			</div>
			<div class="row" style="gap:6px;flex-wrap:nowrap">
				<span class="chip lvl {n.level === 'info' ? '' : n.level}">{t(`lvl.${n.level}`)}</span>
				{#if !n.dismissedAt}<button class="ib" aria-label={t('a.dismiss')} title={t('a.dismiss')} onclick={() => dismiss(n)}><Icon name="check" size={16} /></button>{/if}
			</div>
		</div>
	{:else}
		<p class="dim">{t(view === 'active' ? 'nt.empty' : 'nt.history_empty')}</p>
	{/each}
	<Pages total={list.length} size={SIZE} bind:page={pg} />
</section>

<style>
	@media (max-width: 560px) {
		.lvl {
			display: none;
		}
	}
</style>
