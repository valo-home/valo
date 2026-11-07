<script>
	import { onMount, tick } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { useApp } from '#lib/app.svelte.js';
	import Icon from '#lib/components/Icon.svelte';
	import Hint from '#lib/components/Hint.svelte';
	import Markdown from '#lib/components/Markdown.svelte';

	const app = useApp();
	const { s, t, f } = app;
	const HINTS = ['ai.hint_status', 'ai.hint_board', 'ai.hint_battery', 'ai.hint_pair'];
	let status = $state(null);
	let chats = $state([]);
	let moreChats = $state(false);
	let cur = $state(null);
	let msgs = $state([]);
	let acts = $state({});
	let moreMsgs = $state(false);
	let text = $state('');
	let live = $state('');
	let stepInfo = $state(null);
	let sending = $state(false);
	let renaming = $state('');
	let sure = $state('');
	let feed = $state();
	let box = $state();
	const id = $derived(page.url.searchParams.get('c') || '');
	const running = $derived(cur?.status === 'running');
	const latest = {};
	const newer = (a, b) => (b && b.updatedAt > a.updatedAt ? b : a);
	const lastTool = (m) => m.role === 'tool' && m.data?.action;

	async function loadChats(more = false) {
		const before = more && chats.length ? `&before=${encodeURIComponent(chats.at(-1).updatedAt)}` : '';
		const rows = await app.api('GET', `/chats?limit=40${before}`).catch((e) => (app.toast(e.message, 'crit'), []));
		chats = more ? [...chats, ...rows.filter((r) => !chats.some((c) => c.id === r.id))] : rows;
		moreChats = rows.length === 40;
	}
	async function open(cid) {
		cur = null;
		msgs = [];
		acts = {};
		live = '';
		stepInfo = null;
		if (!cid) return;
		try {
			const d = await app.api('GET', `/chats/${cid}`);
			if (cid !== id) return;
			cur = newer(d.chat, latest[cid]);
			const known = new Set(d.messages.map((m) => m.id));
			msgs = [...d.messages, ...msgs.filter((m) => !known.has(m.id))].sort((a, b) => a.id - b.id);
			acts = { ...Object.fromEntries(d.actions.map((a) => [a.id, a])), ...acts };
			moreMsgs = d.more;
			await scroll(true);
		} catch (e) {
			app.toast(e.message, 'crit');
			goto(app.path('/chat'), { replaceState: true });
		}
	}
	async function older() {
		const d = await app.api('GET', `/chats/${cur.id}?before=${msgs[0].id}`).catch((e) => (app.toast(e.message, 'crit'), null));
		if (d) ((msgs = [...d.messages, ...msgs]), (moreMsgs = d.more));
	}
	async function scroll(force = false) {
		await tick();
		if (!feed) return;
		const near = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 160;
		if (force || near) feed.scrollTop = feed.scrollHeight;
	}
	async function send(value = text) {
		const v = value.trim();
		if (!v || sending || running) return;
		sending = true;
		try {
			let cid = cur?.id;
			const fresh = !cid;
			if (fresh) {
				const c = await app.api('POST', '/chats', {});
				chats = [c, ...chats.filter((x) => x.id !== c.id)];
				cid = c.id;
			}
			const mark = latest[cid];
			const m = await app.api('POST', `/chats/${cid}/messages`, { text: v });
			text = '';
			if (fresh) return void (await goto(app.path(`/chat?c=${cid}`)));
			if (!msgs.some((x) => x.id === m.id)) msgs = [...msgs, m];
			if (cur && latest[cid] === mark) cur.status = 'running';
			await scroll(true);
		} catch (e) {
			app.toast(e.message, 'crit');
		} finally {
			sending = false;
			box?.focus();
		}
	}
	const stop = () => app.run(() => app.api('POST', `/chats/${cur.id}/stop`));
	async function act(a, op) {
		const r = await app.run(() => app.api('POST', `/chats/${cur.id}/actions/${a.id}/${op}`));
		if (r) acts = { ...acts, [r.id]: r };
	}
	async function rename(c, title) {
		renaming = '';
		if (!title.trim() || title === c.title) return;
		const r = await app.run(() => app.api('PATCH', `/chats/${c.id}`, { title }));
		if (r) chats = chats.map((x) => (x.id === r.id ? r : x));
	}
	async function remove(c) {
		if (sure !== c.id) return void (sure = c.id);
		if (await app.run(() => app.api('DELETE', `/chats/${c.id}`))) {
			chats = chats.filter((x) => x.id !== c.id);
			if (cur?.id === c.id) goto(app.path('/chat'));
		}
	}
	function keys(e) {
		if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
			e.preventDefault();
			send();
		}
	}
	const err = (d) => (t.has(`aierr.${d.error}`) ? t(`aierr.${d.error}`, { n: d.detail }) : `${d.error}${d.detail ? `: ${d.detail}` : ''}`);
	const linkOf = (a) => {
		const v = a.result?.value;
		if (!v || typeof v !== 'object' || a.status !== 'done') return '';
		if (typeof v.link === 'string') return v.link;
		return typeof v.deviceId === 'string' ? `/devices/${encodeURIComponent(v.deviceId)}` : '';
	};
	const toolName = (n) => (t.has(`ait.${n}`) ? t(`ait.${n}`) : n);

	$effect(() => {
		open(id);
	});
	$effect(() => {
		if (!id) return;
		const cid = id;
		const unsub = app.sub([`chat:${cid}`]);
		const offs = [
			app.on('chat_msg', (m) => {
				if (m.chatId !== cid) return;
				msgs = msgs.some((x) => x.id === m.id) ? msgs : [...msgs, m];
				if (m.role === 'assistant') live = '';
				scroll();
			}),
			app.on('chat_delta', (d) => d.chat === cid && ((live = d.text), scroll())),
			app.on('chat_step', (d) => d.chat === cid && (stepInfo = d.kind === 'done' ? null : d)),
			app.on('chat_action', (a) => a.chatId === cid && (acts = { ...acts, [a.id]: a }))
		];
		return () => (unsub(), offs.forEach((fn) => fn()));
	});
	onMount(() => {
		app.api('GET', '/ai/status').then((x) => (status = x)).catch((e) => console.warn('ai status failed', e?.message));
		loadChats();
		const offs = [
			app.on('chat', (c) => {
				latest[c.id] = newer(c, latest[c.id]);
				chats = [c, ...chats.filter((x) => x.id !== c.id)].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
				if (cur?.id === c.id) cur = newer(c, cur);
				if (c.status !== 'running' && cur?.id === c.id) ((live = ''), (stepInfo = null));
			}),
			app.on('chat_gone', (c) => ((chats = chats.filter((x) => x.id !== c.id)), cur?.id === c.id && goto(app.path('/chat'))))
		];
		return () => offs.forEach((fn) => fn());
	});
</script>

<svelte:head><title>{t('nav.chat')} · valo</title></svelte:head>

<div class="chatw" class:has={!!id}>
	<aside class="clist card">
		<button class="btn pri" onclick={() => goto(app.path('/chat'))}><Icon name="plus" size={16} />{t('ai.new')}</button>
		<div class="lst">
			{#each chats as c (c.id)}
				<div class="ri citem" class:on={c.id === id}>
					{#if renaming === c.id}
						<input class="in" value={c.title} aria-label={t('ai.rename')} onkeydown={(e) => e.key === 'Enter' && rename(c, e.target.value)} onblur={(e) => rename(c, e.target.value)} />
					{:else}
						<a href={app.path(`/chat?c=${c.id}`)} style="flex:1;min-width:0;color:inherit;text-decoration:none">
							<span class="ct">{c.title || t('ai.untitled')}</span>
							<small class="dim">{c.status === 'running' ? t('ai.answering') : f.ago(c.updatedAt)}</small>
						</a>
						<button class="ib s" aria-label={t('ai.rename')} title={t('ai.rename')} onclick={() => (renaming = c.id)}><Icon name="edit" size={14} /></button>
						<button class="ib s" class:warn={sure === c.id} aria-label={sure === c.id ? t('a.confirm_delete') : t('a.delete')} title={sure === c.id ? t('a.confirm_delete') : t('a.delete')} onclick={() => remove(c)}><Icon name="trash" size={14} /></button>
					{/if}
				</div>
			{:else}<p class="dim sm">{t('ai.no_chats')}</p>{/each}
		</div>
		{#if moreChats}<button class="btn s" onclick={() => loadChats(true)}>{t('pg.more')}</button>{/if}
	</aside>

	<section class="cmain card">
		<header class="row chead">
			<a class="ib back" href={app.path('/chat')} aria-label={t('a.back')}><Icon name="back" size={16} /></a>
			<h1>{cur?.title || t('nav.chat')} <Hint k="p_chat" doc="assistant" /></h1>
			<span class="sp"></span>
			{#if status?.model}<span class="chip m model">{status.model}</span>{/if}
		</header>
		{#if status && !status.ready}
			<div class="banner">
				{t('ai.not_ready')}
				{#if app.can('admin')}<a href={app.path('/system?tab=ai')}>{t('ai.setup')}</a>{/if}
			</div>
		{/if}
		<div class="feed" bind:this={feed} aria-live="polite">
			{#if moreMsgs}<div style="text-align:center"><button class="btn s" onclick={older}>{t('pg.more')}</button></div>{/if}
			{#if !id && !msgs.length}
				<div class="hello">
					<Icon name="spark" size={28} />
					<h2>{t('ai.hello')}</h2>
					<p class="dim">{t('ai.hello_sub')}</p>
					<div class="hints">{#each HINTS as h}<button class="btn" disabled={!status?.ready} onclick={() => send(t(h))}>{t(h)}</button>{/each}</div>
				</div>
			{/if}
			{#each msgs as m (m.id)}
				{#if m.role === 'user'}
					<div class="msg me"><div class="bub">{m.content}</div></div>
				{:else if m.role === 'assistant'}
					{#if m.data?.error}
						<div class="msg ai"><div class="bub errb" role="alert"><Icon name="warn" size={16} /> {err(m.data)}</div></div>
					{:else if m.content}
						<div class="msg ai"><div class="bub"><Markdown text={m.content} /></div></div>
					{/if}
				{:else if m.role === 'tool'}
					<div class="tstep" class:fail={m.data?.ok === false}><Icon name={m.data?.ok === false ? 'warn' : 'check'} size={13} />{toolName(m.data?.name)}</div>
					{#if lastTool(m) && acts[m.data.action]}
						{@const a = acts[m.data.action]}
						<div class="acard {a.status}">
							<div class="row" style="gap:8px"><Icon name={a.status === 'pending' ? 'shield' : a.status === 'done' ? 'check' : a.status === 'failed' ? 'warn' : 'x'} size={16} /><b>{a.summary}</b></div>
							<div class="row sm" style="gap:8px">
								<span class="chip {a.status === 'done' ? 'ok' : a.status === 'failed' ? 'crit' : a.status === 'pending' ? 'amber' : ''}">{t(`ai.st_${a.status}`)}</span>
								{#if linkOf(a)}<a href={app.path(linkOf(a))}>{t('ai.open')}</a>{/if}
								<span class="sp"></span>
								{#if a.status === 'pending'}
									<button class="btn s" onclick={() => act(a, 'reject')}>{t('ai.reject')}</button>
									<button class="btn s pri" onclick={() => act(a, 'confirm')}>{t('ai.confirm')}</button>
								{:else if a.canUndo}
									<button class="btn s" onclick={() => act(a, 'undo')}><Icon name="undo" size={14} />{t('ai.undo')}</button>
								{/if}
							</div>
							{#if a.status === 'failed' && a.result?.error}<div class="sm" style="color:var(--crit)">{t.has(`aierr.${a.result.error}`) ? t(`aierr.${a.result.error}`) : a.result.error}</div>{/if}
						</div>
					{/if}
				{:else if m.role === 'note' && m.data?.kind === 'stopped'}
					<div class="tstep fail"><Icon name="x" size={13} />{t('ai.stopped')}</div>
				{/if}
			{/each}
			{#if live}<div class="msg ai"><div class="bub"><Markdown text={live} /></div></div>{/if}
			{#if running}
				<div class="tstep run"><span class="dots"><i></i><i></i><i></i></span>{stepInfo?.kind === 'tool' ? toolName(stepInfo.tool) : t('ai.thinking')}</div>
			{/if}
		</div>
		<form class="composer" onsubmit={(e) => (e.preventDefault(), send())}>
			<textarea bind:this={box} class="in" rows="1" bind:value={text} placeholder={t('ai.placeholder')} aria-label={t('ai.placeholder')} onkeydown={keys} disabled={!status?.ready}></textarea>
			{#if running}
				<button type="button" class="btn" onclick={stop} aria-label={t('ai.stop')}><Icon name="x" size={16} /><span class="bt">{t('ai.stop')}</span></button>
			{:else}
				<button type="submit" class="btn pri" disabled={!text.trim() || sending || !status?.ready} aria-label={t('ai.send')}><Icon name="send" size={16} /><span class="bt">{t('ai.send')}</span></button>
			{/if}
		</form>
	</section>
</div>

<style>
	.chatw {
		display: grid;
		grid-template-columns: 280px minmax(0, 1fr);
		gap: 16px;
		height: calc(100dvh - 140px);
		min-height: 420px;
	}
	.clist {
		display: flex;
		flex-direction: column;
		gap: 10px;
		overflow: auto;
		padding: 12px;
	}
	.clist > :global(*) {
		flex: none;
	}
	.citem {
		gap: 4px;
	}
	.citem a {
		display: grid;
	}
	.ct {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-weight: 500;
	}
	.ib.s {
		width: 28px;
		height: 28px;
		opacity: 0.6;
	}
	.citem:hover .ib.s,
	.citem.on .ib.s,
	.ib.s:focus-visible {
		opacity: 1;
	}
	.ib.warn {
		color: var(--crit);
		opacity: 1;
	}
	.cmain {
		display: flex;
		flex-direction: column;
		min-height: 0;
		padding: 0;
		overflow: hidden;
	}
	.chead {
		padding: 12px 16px;
		border-bottom: 1px solid var(--line);
		gap: 10px;
		flex-wrap: nowrap;
	}
	.chead h1 {
		flex: 1;
		min-width: 0;
		font-size: 16px;
		margin: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.back {
		display: none;
	}
	.banner {
		padding: 10px 16px;
		background: color-mix(in srgb, var(--amber) 14%, transparent);
		font-size: 13px;
		display: flex;
		gap: 10px;
	}
	.feed {
		flex: 1;
		overflow-y: auto;
		overflow-x: hidden;
		padding: 16px;
		display: flex;
		flex-direction: column;
		gap: 10px;
	}
	.msg {
		display: flex;
	}
	.msg.me {
		justify-content: flex-end;
	}
	.bub {
		max-width: min(720px, 92%);
		padding: 10px 14px;
		border-radius: 14px;
		background: var(--raise);
		border: 1px solid var(--line);
		overflow-wrap: anywhere;
	}
	.me .bub {
		background: color-mix(in srgb, var(--amber) 18%, var(--panel));
		white-space: pre-wrap;
	}
	.errb {
		color: var(--crit);
		display: flex;
		gap: 8px;
		align-items: center;
	}
	.tstep {
		display: flex;
		align-items: center;
		gap: 6px;
		font: 500 11px var(--f-m);
		color: var(--ink-3);
		padding-left: 4px;
	}
	.tstep.fail {
		color: var(--crit);
	}
	.acard {
		display: grid;
		gap: 8px;
		padding: 12px 14px;
		border-radius: 12px;
		border: 1px solid var(--line-2);
		background: var(--panel);
		max-width: min(720px, 92%);
	}
	.acard.pending {
		border-color: var(--amber);
	}
	.hello {
		width: 100%;
		min-width: 0;
		margin: auto;
		text-align: center;
		display: grid;
		gap: 8px;
		justify-items: center;
		max-width: 560px;
	}
	.hello h2 {
		margin: 0;
	}
	.hints .btn {
		white-space: normal;
		height: auto;
		min-height: 36px;
		padding-top: 6px;
		padding-bottom: 6px;
		text-align: center;
	}
	.hints {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		justify-content: center;
		margin-top: 8px;
	}
	.composer {
		display: flex;
		gap: 8px;
		padding: 12px;
		border-top: 1px solid var(--line);
		align-items: flex-end;
	}
	.composer textarea {
		flex: 1;
		resize: none;
		min-height: 40px;
		max-height: 200px;
		field-sizing: content;
		padding-top: 9px;
	}
	.dots {
		display: inline-flex;
		gap: 3px;
	}
	.dots i {
		width: 5px;
		height: 5px;
		border-radius: 50%;
		background: currentColor;
		animation: blink 1.2s infinite;
	}
	.dots i:nth-child(2) {
		animation-delay: 0.2s;
	}
	.dots i:nth-child(3) {
		animation-delay: 0.4s;
	}
	@keyframes blink {
		0%,
		80%,
		100% {
			opacity: 0.25;
		}
		40% {
			opacity: 1;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.dots i {
			animation: none;
		}
	}
	@media (max-width: 860px) {
		.chatw {
			grid-template-columns: 1fr;
			height: calc(100dvh - 190px);
		}
		.chatw.has .clist {
			display: none;
		}
		.chatw:not(.has) {
			grid-template-rows: auto minmax(360px, 1fr);
			height: auto;
		}
		.chatw:not(.has) .clist {
			max-height: 34vh;
		}
		.chatw.has .back {
			display: grid;
		}
		.ib.s {
			width: 36px;
			height: 36px;
			opacity: 1;
		}
		.model,
		.bt {
			display: none;
		}
	}
</style>
