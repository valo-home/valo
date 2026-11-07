<script>
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { createApp } from '#lib/app.svelte.js';
	import { LANGS } from '#lib/i18n/index.js';
	import EnvBadge from '#lib/components/EnvBadge.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import Notifs from '#lib/components/Notifs.svelte';
	import Pair from '#lib/components/Pair.svelte';
	import Palette from '#lib/components/Palette.svelte';

	let { data, children } = $props();
	const app = createApp(() => data).provide();
	const { s, t } = app;
	let side = $state(false);
	let now = $state(Date.now());
	let sys = $state(null);
	let ck = $state();
	let nt = $state();
	let pair = $state();

	const name = (x, fb) => (x && typeof x === 'object' ? x[app.lang] || x.en || Object.values(x)[0] : x || fb);
	const nav = $derived([
		['nav.g_home', [['/', 'nav.home', 'home'], ['/chat', 'nav.chat', 'spark'], ['/boards', 'nav.boards', 'grid'], ['/rooms', 'nav.rooms', 'rooms'], ['/devices', 'nav.devices', 'dev', Object.values(s.devices).filter((d) => !d.service).length], ...(app.can('member') ? [['/cameras', 'nav.cameras', 'camera', Object.values(s.devices).filter((d) => d.kind === 'camera').length || null]] : [])]],
		['nav.g_auto', [['/flows', 'nav.flows', 'flow', s.flows.length]]],
		['nav.g_ext', [['/extensions', 'nav.extensions', 'ext'], ...(s.contrib?.pages || []).map((p) => [`/x/${p.ext}/${p.key}`, name(p.name, p.key), p.icon || 'ext', null, true])]],
		['nav.g_sys', [...(app.can('admin') ? [['/zigbee', 'nav.zigbee', 'zig'], ['/mqtt', 'nav.mqtt', 'mqtt']] : []), ['/log', 'nav.log', 'log'], ['/system', 'nav.system', 'sliders'], ['/docs', 'nav.docs', 'book']]]
	]);
	const INLINE = 3;
	const extPages = $derived((s.contrib?.pages || []).length);
	let extOpen = $state(false);
	const extShown = $derived(extPages <= INLINE || extOpen || rel.startsWith('/x/'));
	function toggleExt() {
		extOpen = !extShown;
		try {
			localStorage.setItem('valo.nav.ext', extOpen ? '1' : '0');
		} catch (e) {
			console.warn('nav state not saved', e?.message);
		}
	}
	const flat = $derived(nav.flatMap(([, items]) => items).map(([p, l, i, , x]) => ({ href: app.path(p), label: x ? l : t(l), icon: i })));
	const rel = $derived(page.url.pathname.slice(app.lang.length + 1) || '/');
	const on = (p) => (p === '/' ? rel === '/' : rel === p || rel.startsWith(`${p}/`));
	const current = $derived(flat.find((x) => x.href !== app.path('/') && page.url.pathname.startsWith(x.href)) || flat[0]);
	const errs = $derived((sys?.extensions || []).filter((x) => x.status === 'error').length);
	const initials = $derived(s.me.name.split(/\s+/).map((w) => w[0]).slice(0, 2).join('').toUpperCase());

	async function health() {
		sys = await app.api('GET', '/system').catch((e) => (console.warn('system status failed', e?.message), sys));
	}
	let reported = 0;
	const FOREIGN = /(chrome|moz|safari|safari-web)-extension:\/\/|webkit-masked-url:/;
	const ours = (file, stack) => !(file && !file.startsWith(location.origin)) && !(FOREIGN.test(String(stack || '')) && !String(stack).includes('/_app/'));
	function report(message, stack, file = '') {
		if (!ours(file, stack) || String(message).startsWith('Script error')) return;
		if (reported++ >= 10 || !message) return;
		app.api('POST', '/system/errors/report', { source: 'browser', message: String(message).slice(0, 300), stack: String(stack || '').slice(0, 6000), url: location.pathname + location.search }).catch(() => {});
	}
	onMount(() => {
		const onErr = (e) => report(e.message, e.error?.stack, e.filename);
		const onRej = (e) => report(e.reason?.message || e.reason, e.reason?.stack);
		addEventListener('error', onErr);
		addEventListener('unhandledrejection', onRej);
		try {
			extOpen = localStorage.getItem('valo.nav.ext') === '1';
		} catch (e) {
			console.warn('nav state unavailable', e?.message);
		}
		app.pair = (room) => pair.show(room);
		app.connect();
		health();
		const offs = [app.on('zigbee', (d) => d?.type === 'state' && health()), app.on('ext', health), app.on('ext_gone', health)];
		const i = setInterval(() => (now = Date.now()), 15000);
		const h = setInterval(health, 60000);
		const key = (e) => {
			if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') (e.preventDefault(), ck.show());
		};
		addEventListener('keydown', key);
		return () => (app.close(), offs.forEach((f) => f()), clearInterval(i), clearInterval(h), removeEventListener('keydown', key), removeEventListener('error', onErr), removeEventListener('unhandledrejection', onRej));
	});
	$effect(() => {
		page.url.pathname;
		side = false;
	});
</script>

<div id="app">
	<aside id="side" class:open={side}>
		<div class="brand"><div class="logo"></div><div><b>valo</b><small>{t('brand.sub')}</small></div></div>
		<div style="padding:0 8px"><EnvBadge env={s.env} {t} /></div>
		<button class="homesel" onclick={() => ck.show()}>
			<span><b>{s.home.name}</b><small>{s.home.timezone}</small></span><Icon name="search" size={16} />
		</button>
		<nav class="nav" aria-label={t('nav.aria')}>
			{#each nav as [g, items]}
				<h6>{t(g)}</h6>
				{#each items as [p, l, i, cnt, x], k}
					{#if x && k === 1 && extPages > INLINE}
						<button type="button" class="grp" aria-expanded={extShown} onclick={toggleExt}><Icon name="layers" />{t('nav.ext_pages')}<span class="cnt">{extPages}</span><span class="chv" class:open={extShown}><Icon name="chev" size={14} /></span></button>
					{/if}
					{#if !x || extShown}
						<a href={app.path(p === '/' ? '' : p)} class:on={on(p)} class:sub={x} aria-current={on(p) ? 'page' : undefined}>
							<Icon name={i} /><span class="nl">{x ? l : t(l)}</span>
							{#if cnt != null}<span class="cnt">{cnt}</span>{/if}
						</a>
					{/if}
				{/each}
			{/each}
		</nav>
		<div class="sfoot">
			<div class="health">
				<div><i class="dot" class:crit={!s.online}></i>{t('h.live')}<em>{s.online ? t('h.online') : t('h.offline')}</em></div>
				{#if sys}
					<div><i class="dot" class:crit={!sys.health.mqtt}></i>{t('h.broker')}<em>{sys.versions.mosquitto?.replace('mosquitto version ', '') || '-'}</em></div>
					<div><i class="dot" class:crit={sys.health.zigbee !== 'online'}></i>Zigbee<em>{t(`zs.${sys.health.zigbee}`)}</em></div>
					<div><i class="dot" class:crit={errs > 0} class:off={!sys.health.ext}></i>{t('h.ext')}<em>{errs ? t('h.errors', { n: errs }) : t('h.ok')}</em></div>
					{#if app.can('admin')}<a href={app.path('/system?tab=errors')} style="display:flex;align-items:center;gap:8px;color:inherit;text-decoration:none"><i class="dot" class:crit={sys.errors > 0}></i>{t('h.err_log')}<em>{sys.errors ? t('h.new', { n: sys.errors }) : t('h.ok')}</em></a>{/if}
				{/if}
			</div>
			<select class="in" style="height:30px;font-size:12px" aria-label={t('sys.lang')} value={app.lang} onchange={(e) => (location.href = `/${e.target.value}${page.url.pathname.slice(app.lang.length + 1)}`)}>
				{#each LANGS as l}<option value={l}>{t(`lang.${l}`)}</option>{/each}
			</select>
			<form method="POST" action={app.path('/logout')}>
				<button class="me" title={t('a.logout')}>
					<span class="ava">{initials}</span>
					<span style="flex:1;min-width:0"><b style="font-weight:500;display:block">{s.me.name}</b><small class="dim">{t(`role.${s.me.role}`)}</small></span>
					<Icon name="logout" size={16} />
				</button>
			</form>
		</div>
	</aside>
	<main style="min-width:0">
		<header id="top">
			<button class="ib menu-b" aria-label={t('a.menu')} onclick={() => (side = !side)}><Icon name="menu" /></button>
			<div class="crumbs">{s.home.name} › <b>{current.label}</b></div>
			<span class="env-top"><EnvBadge env={s.env} {t} peers={false} /></span>
			<span class="clock">{app.f.head(now)} · {app.f.time(now)}</span>
			<button class="cmd" onclick={() => ck.show()}><Icon name="search" size={16} /><span>{t('ck.open')}</span><kbd>Ctrl K</kbd></button>
			{#if app.can('admin')}<button class="btn pri addb" onclick={() => pair.show()}><Icon name="plus" size={16} /><span>{t('pair.title')}</span></button>{/if}
			<button class="ib" aria-label={t('nt.title')} onclick={() => nt.show()}><Icon name="bell" />{#if s.notifs.length}<span class="bd">{s.notifs.length}</span>{/if}</button>
		</header>
		<div id="page">{@render children()}</div>
	</main>
</div>
{#if side}<div class="scrim" style="position:fixed;inset:0;background:var(--scrim);z-index:60" role="presentation" onclick={() => (side = false)}></div>{/if}
<nav id="tabbar" aria-label={t('nav.aria')}>
	{#each [['/', 'nav.home', 'home'], ['/chat', 'nav.chat', 'spark'], ['/devices', 'nav.devices', 'dev'], ['/flows', 'nav.flows', 'flow']] as [p, l, i]}
		<a href={app.path(p === '/' ? '' : p)} class:on={on(p)}><Icon name={i} size={20} />{t(l)}</a>
	{/each}
	<button onclick={() => (side = true)}><Icon name="menu" size={20} />{t('a.menu')}</button>
</nav>
<div id="toasts" aria-live="polite">
	{#each s.toasts as x (x.id)}<div class="toast {x.level}"><Icon name={x.level === 'ok' ? 'check' : 'warn'} size={16} /><span>{x.text}</span></div>{/each}
</div>
<Palette bind:this={ck} pages={flat} />
<Notifs bind:this={nt} />
<Pair bind:this={pair} />
