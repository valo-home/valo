<script>
	import { page } from '$app/state';
	import { useApp } from '#lib/app.svelte.js';
	import Icon from '#lib/components/Icon.svelte';
	import Markdown from '#lib/components/Markdown.svelte';

	const app = useApp();
	const { t } = app;
	let idx = $state({ sections: [], extensions: [] });
	let doc = $state(null);
	let missing = $state(false);
	let q = $state('');
	let hits = $state(null);
	let timer;
	const path = $derived(page.params.path || '');
	const extId = $derived(path.startsWith('ext/') ? path.slice(4) : '');
	const flat = $derived(idx.sections.flatMap((s) => s.pages));
	const at = $derived(flat.findIndex((p) => p.slug === path));
	const body = $derived(doc ? doc.text.replace(/^# .*\n+/, '') : '');

	$effect(() => {
		const lang = app.lang;
		app.api('GET', `/help?lang=${lang}`)
			.then((r) => (idx = r))
			.catch((e) => console.warn('help index failed', e?.message));
	});
	$effect(() => {
		const p = path;
		const lang = app.lang;
		missing = false;
		if (!p) return void (doc = null);
		const ext = p.startsWith('ext/') ? p.slice(4) : '';
		const req = ext ? app.api('GET', `/extensions/${encodeURIComponent(ext)}/docs?lang=${lang}`) : app.api('GET', `/help/${encodeURIComponent(p)}?lang=${lang}`);
		req
			.then((r) => {
				if (p !== path) return;
				const name = ext ? idx.extensions.find((x) => x.id === ext)?.name || ext : '';
				doc = ext ? { title: name, text: r.text ? `# ${name}\n\n${r.text}` : '' } : r;
				missing = !doc.text;
				document.getElementById('page')?.scrollTo?.(0, 0);
				requestAnimationFrame(() => document.querySelector('.ddesk a[aria-current=page]')?.scrollIntoView({ block: 'nearest' }));
			})
			.catch(() => ((doc = null), (missing = true)));
	});
	function find() {
		clearTimeout(timer);
		const v = q.trim();
		if (v.length < 2) return void (hits = null);
		timer = setTimeout(() => {
			app.api('GET', `/help?lang=${app.lang}&q=${encodeURIComponent(v)}`)
				.then((r) => q.trim() === v && (hits = r.hits))
				.catch((e) => console.warn('help search failed', e?.message));
		}, 250);
	}
</script>

<svelte:head><title>{doc?.title ? `${doc.title} · ` : ''}{t('nav.docs')} · valo</title></svelte:head>

{#snippet nav()}
	<nav class="dnav" aria-label={t('docs.contents')}>
		<a href={app.path('/docs')} class:on={!path} aria-current={!path ? 'page' : undefined}><Icon name="book" size={15} />{t('docs.all')}</a>
		{#each idx.sections as s (s.key)}
			<div class="lbl">{s.title}</div>
			{#each s.pages as p (p.slug)}<a href={app.path(`/docs/${p.slug}`)} class:on={path === p.slug} aria-current={path === p.slug ? 'page' : undefined}>{p.title}</a>{/each}
		{/each}
		{#if idx.extensions.length}
			<div class="lbl">{t('docs.ext')}</div>
			{#each idx.extensions as x (x.id)}<a href={app.path(`/docs/ext/${x.id}`)} class:on={extId === x.id} aria-current={extId === x.id ? 'page' : undefined}>{x.name}</a>{/each}
		{/if}
	</nav>
{/snippet}

<div class="ph">
	<div class="row" style="gap:12px;flex-wrap:nowrap;min-width:0">
		{#if path}<a class="btn ghost" href={app.path('/docs')} aria-label={t('docs.all')} title={t('docs.all')}><Icon name="back" size={16} /></a>{/if}
		<div style="min-width:0"><h1>{path ? doc?.title || t('nav.docs') : t('nav.docs')}</h1><p>{path ? t('nav.docs') : t('docs.sub')}</p></div>
	</div>
</div>

<div class="dk">
	<aside class="dside">
		<details class="dmob">
			<summary class="btn"><Icon name="menu" size={16} />{t('docs.contents')}</summary>
			{@render nav()}
		</details>
		<div class="ddesk">{@render nav()}</div>
	</aside>
	<div class="g" style="gap:16px;min-width:0">
		{#if !path}
			<input class="in" type="search" placeholder={t('docs.search')} aria-label={t('docs.search')} bind:value={q} oninput={find} />
			{#if hits}
				<section class="card g" style="gap:4px">
					{#each hits as h (h.slug)}<a class="hit" href={app.path(`/docs/${h.slug}`)}><b>{h.title}</b><span class="sm dim">{h.text}</span></a>{:else}<p class="dim" style="margin:0">{t('docs.none')}</p>{/each}
				</section>
			{:else}
				<div class="dgrid">
					{#each idx.sections as s (s.key)}
						<section class="card">
							<h3>{s.title}</h3>
							<div class="g" style="gap:2px">{#each s.pages as p (p.slug)}<a class="ln" href={app.path(`/docs/${p.slug}`)}>{p.title}<Icon name="chev" size={14} /></a>{/each}</div>
						</section>
					{/each}
					{#if idx.extensions.length}
						<section class="card">
							<h3>{t('docs.ext')}</h3>
							<div class="g" style="gap:2px">{#each idx.extensions as x (x.id)}<a class="ln" href={app.path(`/docs/ext/${x.id}`)}>{x.name}<Icon name="chev" size={14} /></a>{/each}</div>
						</section>
					{/if}
				</div>
			{/if}
		{:else if missing}
			<div class="empty">{t('docs.missing')} <a href={app.path('/docs')}>{t('docs.all')}</a></div>
		{:else if doc}
			<article class="card doc"><Markdown text={body} /></article>
			{#if at >= 0}
				<div class="row" style="justify-content:space-between">
					{#if at > 0}<a class="btn ghost" href={app.path(`/docs/${flat[at - 1].slug}`)}><Icon name="back" size={16} />{flat[at - 1].title}</a>{:else}<span></span>{/if}
					{#if at < flat.length - 1}<a class="btn ghost" href={app.path(`/docs/${flat[at + 1].slug}`)}>{flat[at + 1].title}<Icon name="chev" size={16} /></a>{/if}
				</div>
			{/if}
		{:else}
			<div class="dim">{t('w.loading')}</div>
		{/if}
	</div>
</div>

<style>
	.dk {
		display: grid;
		grid-template-columns: 230px minmax(0, 1fr);
		gap: 20px;
		align-items: start;
	}
	.dside {
		position: sticky;
		top: 76px;
		max-height: calc(100vh - 96px);
		overflow: auto;
	}
	.dnav {
		display: grid;
		gap: 2px;
	}
	.dnav .lbl {
		margin: 12px 10px 4px;
	}
	.dnav a {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 6px 10px;
		border-radius: 8px;
		color: var(--ink-2);
		text-decoration: none;
		font-size: 13.5px;
	}
	.dnav a:hover {
		background: var(--raise);
		color: var(--ink);
	}
	.dnav a.on {
		background: var(--raise);
		color: var(--ink);
		font-weight: 600;
	}
	.dmob {
		display: none;
	}
	.dgrid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(min(280px, 100%), 1fr));
		gap: 16px;
	}
	.ln {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		padding: 7px 8px;
		margin: 0 -8px;
		border-radius: 8px;
		color: var(--ink);
	}
	.ln:hover {
		background: var(--raise);
		text-decoration: none !important;
	}
	.hit {
		display: grid;
		gap: 2px;
		padding: 9px 10px;
		border-radius: 8px;
		color: var(--ink);
	}
	.hit:hover {
		background: var(--raise);
		text-decoration: none !important;
	}
	.doc {
		padding: 22px 26px;
		max-width: 860px;
		font-size: 14.5px;
	}
	@media (max-width: 900px) {
		.dk {
			grid-template-columns: minmax(0, 1fr);
			gap: 12px;
		}
		.dside {
			position: static;
			max-height: none;
		}
		.dmob {
			display: block;
		}
		.dmob[open] .dnav {
			margin-top: 8px;
			padding: 8px;
			border: 1px solid var(--line);
			border-radius: var(--r);
			background: var(--panel);
		}
		.ddesk {
			display: none;
		}
		.doc {
			padding: 16px;
		}
	}
</style>
