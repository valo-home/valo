<script>
	import { page } from '$app/state';
	import { useApp } from '#lib/app.svelte.js';
	import { actor, evText, levelIcon, notifText, route, routeName } from '#lib/events.js';
	import Icon from '#lib/components/Icon.svelte';
	import Hint from '#lib/components/Hint.svelte';

	const app = useApp();
	const { t, f } = app;
	let n = $state(null);
	let missing = $state(false);
	const id = $derived(+page.params.id);
	async function load() {
		try {
			n = await app.api('GET', `/notifications/${id}`);
			missing = false;
		} catch (e) {
			console.warn('notification load failed', id, e);
			missing = true;
		}
	}
	$effect(() => {
		id;
		load();
	});
	$effect(() => {
		const mine = (d) => d.id === id && load();
		const off = [app.on('notif', mine), app.on('notif_gone', mine)];
		return () => off.forEach((x) => x());
	});
	const dismiss = () => app.run(() => app.api('POST', `/notifications/${id}/dismiss`)).then(load);
	const color = (l) => `var(--${l === 'info' ? 'frost' : l})`;
</script>

<svelte:head><title>{t('nt.one')} · valo</title></svelte:head>

{#if missing}
	<div class="empty">{t('nt.missing')} <a href={app.path('/notifications')}>{t('nt.all')}</a></div>
{:else if n}
	<div class="ph">
		<div class="row" style="gap:14px;flex-wrap:nowrap;min-width:0">
			<a class="btn ghost" href={app.path('/notifications')} aria-label={t('a.back')} title={t('nt.all')}><Icon name="back" size={16} /></a>
			<div class="dico" style="width:48px;height:48px;border-radius:14px;color:{color(n.level)}"><Icon name={levelIcon(n.level)} size={24} /></div>
			<div style="min-width:0">
				<h1>{t('nt.one')} <Hint k="p_notifications" doc="log" /></h1>
				<p class="meta"><span class="chip {n.level === 'info' ? '' : n.level}">{t(`lvl.${n.level}`)}</span><span>{f.stamp(n.createdAt)}</span>{#if n.dismissedAt}<span>{t('nt.closed', { time: f.ago(n.dismissedAt) })}</span>{:else}<span class="chip warn">{t('nt.open_now')}</span>{/if}</p>
			</div>
		</div>
	</div>

	<div class="g2">
		<section class="card g" style="gap:14px;align-content:start">
			<p style="margin:0;font-size:17px;line-height:1.45;overflow-wrap:anywhere;color:{n.level === 'info' ? 'var(--ink)' : color(n.level)}">{notifText(app, n)}</p>
			<dl class="kv">
				<dt>{t('nt.time')}</dt><dd>{f.stamp(n.createdAt)}, {f.ago(n.createdAt)}</dd>
				<dt>{t('nt.state')}</dt><dd>{n.dismissedAt ? t('nt.closed', { time: f.stamp(n.dismissedAt) }) : t('nt.open_now')}</dd>
				<dt>{t('nt.source')}</dt><dd><a href={route(app, n.route)}>{routeName(app, n.route)}</a></dd>
			</dl>
			<div class="row">
				<a class="btn pri" href={route(app, n.route)}><Icon name="link" size={16} />{t('nt.go')}</a>
				{#if !n.dismissedAt}<button class="btn" onclick={dismiss}><Icon name="check" size={16} />{t('a.dismiss')}</button>{/if}
			</div>
			<details>
				<summary class="sm dim">{t('nt.tech')}</summary>
				<pre class="mono sm" style="white-space:pre-wrap;overflow-wrap:anywhere;margin:8px 0 0">{JSON.stringify({ key: n.key, type: n.type, route: n.route, params: n.params }, null, 2)}</pre>
			</details>
		</section>
		<div class="g" style="gap:14px;align-content:start">
			{#if n.log.length}
				<section class="card g" style="gap:10px">
					<h3><Icon name="terminal" size={16} />{t('nt.ext_log')}</h3>
					<pre class="mono sm" style="white-space:pre-wrap;overflow-wrap:anywhere;margin:0;max-height:360px;overflow:auto">{n.log.join('\n')}</pre>
				</section>
			{/if}
			<section class="card">
				<h3><Icon name="log" size={16} />{t('nt.related')}</h3>
				<p class="sm dim" style="margin:4px 0 8px">{t('nt.related_hint')}</p>
				{#each n.events as e (e.id)}
					<div class="ev lg {e.level}">
						<time>{f.stamp(e.ts)}</time>
						<div style="min-width:0"><b style="overflow-wrap:anywhere">{evText(app, e)}</b><span class="why">{actor(app, e.actor)}</span></div>
						<span></span>
					</div>
				{:else}
					<p class="dim sm">{t('nt.related_empty')}</p>
				{/each}
			</section>
		</div>
	</div>
{/if}
