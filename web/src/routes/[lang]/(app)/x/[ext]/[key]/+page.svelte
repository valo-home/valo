<script>
	import { page } from '$app/state';
	import { useApp } from '#lib/app.svelte.js';
	import Blocks from '#lib/components/Blocks.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import Hint from '#lib/components/Hint.svelte';

	const app = useApp();
	const { s, t, f } = app;
	const pg = $derived(s.contrib?.pages?.find((p) => p.ext === page.params.ext && p.key === page.params.key));
	const tx = (x) => (x && typeof x === 'object' ? (x[app.lang] ?? x.en ?? Object.values(x)[0]) : (x ?? ''));
	let data = $state(null);
	let err = $state('');
	async function action(key) {
		try {
			data = await app.api('POST', `/extensions/${pg.ext}/page/${pg.key}`, { lang: app.lang, action: key });
			err = '';
		} catch (e) {
			app.toast(e.message, 'crit');
		}
	}

	$effect(() => {
		if (!pg || pg.level === 'isolated') return;
		const { ext, key } = pg;
		let alive = true;
		let seq = 0;
		data = null;
		err = '';
		const load = () => {
			const n = ++seq;
			return app
				.api('POST', `/extensions/${ext}/page/${key}`, { lang: app.lang })
				.then((r) => alive && n === seq && ((data = r), (err = '')))
				.catch((e) => alive && n === seq && (err = e.message));
		};
		load();
		const off = app.on('ext_page', (e) => e?.ext === ext && e.keys?.includes(key) && load());
		const i = setInterval(load, 600000);
		return () => ((alive = false), off(), clearInterval(i));
	});
</script>

<svelte:head><title>{pg ? tx(pg.name) : t('nav.extensions')} · valo</title></svelte:head>

{#if !pg}
	<div class="empty">{t('x.missing')} <a href={app.path('/extensions')}>{t('nav.extensions')}</a></div>
{:else}
	<div class="ph">
		<div><h1>{tx(pg.name)} <Hint k="p_xpage" doc="extensions" /></h1><p>{t('x.from', { name: tx(pg.extName) || pg.ext })}{#if data?.updated}{` · ${t('x.updated', { v: f.time(data.updated) })}`}{/if}</p></div>
		<a class="btn" href={app.path(`/extensions?open=${pg.ext}`)}><Icon name="ext" size={16} />{t('x.settings')}</a>
	</div>
	{#if pg.level === 'isolated'}
		<section class="card iso"><iframe title={tx(pg.name)} src="/api/v1/extensions/{pg.ext}/ui/{pg.entry}" sandbox="allow-scripts" style="width:100%;height:70vh;border:0"></iframe></section>
	{:else if err}
		<div class="empty err">{err}</div>
	{:else if data}
		<section class="card"><Blocks blocks={data.blocks || []} onaction={app.can('member') ? action : null} /></section>
	{:else}
		<div class="empty">{t('w.loading')}</div>
	{/if}
{/if}
