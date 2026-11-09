<script>
	import { useApp } from '#lib/app.svelte.js';
	import { levelIcon, notifText, route, routeName } from '#lib/events.js';
	import Icon from './Icon.svelte';
	import Modal from './Modal.svelte';

	const app = useApp();
	const { s, t, f } = app;
	let m = $state();
	export const show = () => m.show();
	const order = { crit: 0, warn: 1, ok: 2, info: 3 };
	const list = $derived([...s.notifs].sort((a, b) => order[a.level] - order[b.level] || b.createdAt.localeCompare(a.createdAt)));
</script>

<Modal bind:this={m} kind="drawer" icon="bell" title={t('nt.title')} sub={t('nt.count', { n: s.notifs.length })}>
	<div class="lst">
		{#each list as n (n.id)}
			<div class="drow" style="grid-template-columns:32px minmax(0,1fr) auto">
				<div class="dico" style="color:var(--{n.level === 'info' ? 'frost' : n.level})"><Icon name={levelIcon(n.level)} size={17} /></div>
				<div style="min-width:0">
					<a class="dn" href={app.path(`/notifications/${n.id}`)} onclick={() => m.hide()} style="white-space:normal">{notifText(app, n)}</a>
					<div class="ds">{f.ago(n.createdAt)} · <a href={route(app, n.route)} onclick={() => m.hide()}>{routeName(app, n.route)}</a></div>
				</div>
				<button class="ib" aria-label={t('a.dismiss')} onclick={() => app.run(() => app.api('POST', `/notifications/${n.id}/dismiss`))}><Icon name="check" size={16} /></button>
			</div>
		{:else}
			<p class="dim">{t('nt.empty')}</p>
		{/each}
	</div>
	<a class="btn" style="margin-top:14px" href={app.path('/notifications')} onclick={() => m.hide()}><Icon name="log" size={16} />{t('nt.all')}</a>
</Modal>
