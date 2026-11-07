<script>
	import { pager } from '#lib/components/pager.svelte.js';
	import More from '#lib/components/More.svelte';
	import '@xyflow/svelte/dist/style.css';
	import { setContext } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { Background, Controls, SvelteFlow } from '@xyflow/svelte';
	import { useApp } from '#lib/app.svelte.js';
	import { copyNodes, pasteNodes } from '#lib/flowclip.js';
	import { KIND_COLOR, blockName, traceText } from '#lib/flowtext.js';
	import FlowFit from '#lib/components/FlowFit.svelte';
	import FlowNode from '#lib/components/FlowNode.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import ParamField from '#lib/components/ParamField.svelte';
	import Toggle from '#lib/components/Toggle.svelte';

	const app = useApp();
	const { s, t, f } = app;
	const id = $derived(page.params.id);
	const reg = $state({ blocks: {} });
	setContext('flowreg', reg);
	const nodeTypes = { block: FlowNode };
	const GROUPS = ['trig', 'cond', 'logic', 'act', 'xf'];
	let flow = $state(null);
	let nodes = $state.raw([]);
	let edges = $state.raw([]);
	let meta = $state({ name: '', mode: 'single', enabled: true });
	let sel = $state(null);
	let dirty = $state(false);
	let side = $state('node');
	let result = $state(null);
	const rnp = pager(app, (b, n) => `/flows/${id}/runs?limit=${n}${b ? `&before=${encodeURIComponent(b)}` : ''}`, (x) => `${x.startedAt}|${x.id}`, 20);
	let versions = $state([]);
	let sure = $state(false);
	const node = $derived(nodes.find((n) => n.id === sel));
	const def = $derived(node ? reg.blocks[node.data.block] : null);
	const admin = app.can('admin');
	const HISTORY = 100;
	let past = $state([]);
	let future = $state([]);
	let last = '';
	let paramAt = 0;

	const ser = () =>
		JSON.stringify({
			nodes: nodes.map((n) => ({ id: n.id, position: { x: Math.round(n.position.x), y: Math.round(n.position.y) }, data: { block: n.data.block, params: n.data.params } })),
			edges: edges.map((e) => ({ id: e.id, source: e.source, target: e.target, sourceHandle: e.sourceHandle, targetHandle: e.targetHandle }))
		});
	function commit() {
		const cur = ser();
		if (cur === last) return;
		past = [...past, last].slice(-HISTORY);
		future = [];
		last = cur;
		dirty = true;
	}
	function apply(state) {
		const g = JSON.parse(state);
		nodes = g.nodes.map((n) => ({ ...n, type: 'block' }));
		edges = g.edges;
		last = state;
		if (sel && !nodes.some((n) => n.id === sel)) sel = null;
		dirty = true;
	}
	function undo() {
		if (!past.length) return;
		future = [ser(), ...future].slice(0, HISTORY);
		const prev = past[past.length - 1];
		past = past.slice(0, -1);
		apply(prev);
	}
	function redo() {
		if (!future.length) return;
		past = [...past, ser()].slice(-HISTORY);
		const next = future[0];
		future = future.slice(1);
		apply(next);
	}
	const picked = () => {
		const ids = nodes.filter((n) => n.selected).map((n) => n.id);
		return ids.length ? ids : sel ? [sel] : [];
	};
	function copy() {
		const n = copyNodes(nodes, edges, picked());
		if (n) app.toast(t('fl.copied', { n }));
	}
	function paste() {
		const { added, links } = pasteNodes(nodes);
		if (!added.length) return;
		nodes = [...nodes.map((n) => ({ ...n, selected: false })), ...added];
		edges = [...edges, ...links];
		sel = added.length === 1 ? added[0].id : null;
		side = 'node';
		commit();
	}
	function duplicate() {
		if (copyNodes(nodes, edges, picked())) paste();
	}
	function keys(e) {
		if (!admin) return;
		const tag = e.target?.tagName;
		if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || e.target?.isContentEditable) return;
		if (!(e.ctrlKey || e.metaKey)) return;
		const k = e.key.toLowerCase();
		const act = k === 'z' && !e.shiftKey ? undo : (k === 'z' && e.shiftKey) || k === 'y' ? redo : k === 'c' ? copy : k === 'v' ? paste : k === 'd' ? duplicate : null;
		if (act) (e.preventDefault(), act());
	}

	const toFlow = (g) => ({
		nodes: (g.nodes || []).map((n) => ({ id: n.id, type: 'block', position: { x: n.x ?? 0, y: n.y ?? 0 }, data: { block: n.block, params: n.params || {} } })),
		edges: (g.edges || []).map((e) => ({ id: `${e.from}:${e.out ?? 0}>${e.to}:${e.in ?? 0}`, source: e.from, target: e.to, sourceHandle: `o${e.out ?? 0}`, targetHandle: `i${e.in ?? 0}` }))
	});
	const toGraph = () => ({
		nodes: nodes.map((n) => ({ id: n.id, block: n.data.block, params: n.data.params, x: Math.round(n.position.x), y: Math.round(n.position.y) })),
		edges: edges.map((e) => ({ from: e.source, out: +(e.sourceHandle || 'o0').slice(1), to: e.target, in: +(e.targetHandle || 'i0').slice(1) }))
	});
	function load(fl) {
		flow = fl;
		meta = { name: fl.name, mode: fl.mode, enabled: fl.enabled };
		({ nodes, edges } = toFlow(fl.graph));
		dirty = false;
		past = [];
		future = [];
		last = ser();
		result = null;
	}
	function paint(r) {
		result = r;
		const st = {};
		for (const e of r?.trace || []) st[e.n] = e.s === 'no' ? 'ok' : e.s;
		const lit = new Set(r?.lit || []);
		nodes = nodes.map((n) => ({ ...n, data: { ...n.data, st: st[n.id] } }));
		edges = edges.map((e) => ({ ...e, class: lit.has(`${e.source}>${e.target}`) ? 'lit' : '' }));
	}

	$effect(() => {
		const fid = id;
		rnp.reset();
		Promise.all([app.api('GET', `/flows/${fid}`), app.api('GET', '/blocks')])
			.then(([fl, bl]) => {
				if (fid !== id) return;
				reg.blocks = Object.fromEntries(bl.map((b) => [b.key, b]));
				load(fl);
			})
			.catch((e) => app.toast(e.message, 'crit'));
		const offs = [
			app.sub([`flow:${fid}`]),
			app.on('run', (r) => {
				if (r.flow !== fid) return;
				const old = rnp.st.items.find((x) => x.id === r.id);
				rnp.push({ startedAt: new Date().toISOString(), ...old, id: r.id, status: r.status, trace: r.trace });
				if (!dirty) paint(r);
			}),
			app.on('flow', (x) => x.id === fid && !dirty && load(x))
		];
		return () => offs.forEach((fn) => fn());
	});

	function add(key) {
		const b = reg.blocks[key];
		const params = Object.fromEntries((b.params || []).filter((p) => p.default !== undefined).map((p) => [p.key, p.default]));
		let nid = key.split(':').pop().slice(0, 3);
		for (let i = 1; nodes.some((n) => n.id === nid); i++) nid = `${key.split(':').pop().slice(0, 3)}${i}`;
		const x = 40 + ((nodes.length * 60) % 600);
		nodes = [...nodes, { id: nid, type: 'block', position: { x, y: 40 + ((nodes.length * 90) % 400) }, data: { block: key, params } }];
		sel = nid;
		side = 'node';
		commit();
	}
	function setParam(k, v) {
		const now = Date.now();
		const merge = now - paramAt < 800 && past.length;
		paramAt = now;
		nodes = nodes.map((n) => (n.id === sel ? { ...n, data: { ...n.data, params: { ...n.data.params, [k]: v } } } : n));
		if (merge) {
			last = ser();
			dirty = true;
		} else commit();
	}
	function removeNode() {
		edges = edges.filter((e) => e.source !== sel && e.target !== sel);
		nodes = nodes.filter((n) => n.id !== sel);
		sel = null;
		commit();
	}
	function valid(c) {
		const a = nodes.find((n) => n.id === c.source);
		const b = nodes.find((n) => n.id === c.target);
		if (!a || !b || a.id === b.id) return false;
		const src = reg.blocks[a.data.block]?.outs?.[+(c.sourceHandle || 'o0').slice(1)];
		const dst = reg.blocks[b.data.block]?.ins?.[+(c.targetHandle || 'i0').slice(1)];
		return !src || !dst || src === dst || src === 'any' || dst === 'any';
	}
	async function save() {
		const r = await app.run(() => app.api('PATCH', `/flows/${id}`, { ...meta, graph: toGraph() }), t('fl.saved'));
		if (r) (load(r), app.api('GET', `/flows/${id}/versions`).then((v) => (versions = v)));
	}
	async function test() {
		const r = await app.run(() => app.api('POST', `/flows/${id}/test`, { graph: toGraph(), node: sel && reg.blocks[node?.data.block]?.kind === 'trig' ? sel : null }));
		if (r) ((side = 'test'), paint(r));
	}
	async function del() {
		if (!sure) return void (sure = true);
		if (await app.run(() => app.api('DELETE', `/flows/${id}`), t('fl.deleted'))) goto(app.path('/flows'));
	}
	async function showVersions() {
		side = 'versions';
		versions = await app.api('GET', `/flows/${id}/versions`).catch(() => []);
	}
	async function restore(v) {
		const r = await app.run(() => app.api('POST', `/flows/${id}/versions/${v}/restore`), t('fl.restored', { v }));
		if (r) load(r);
	}
	const icons = { ok: ['check', 'o'], no: ['x', 'w'], fail: ['warn', 'x'], wait: ['clock', 'w'], skip: ['chev', ''] };
</script>

<svelte:head><title>{meta.name || t('fl.title')} · valo</title></svelte:head>
<svelte:window onkeydown={keys} />

{#snippet traceList(list)}
	<div class="trace">
		{#each list || [] as e, i (i)}
			{@const [ic, cls] = icons[e.s] || ['chev', '']}
			<div><span class={cls}><Icon name={ic} size={14} /></span><span>{traceText(app, e)} <span class="mono sm dim">{e.n}</span></span></div>
		{:else}<span class="dim sm">{t('fl.no_trace')}</span>{/each}
	</div>
{/snippet}

<div class="ftb">
	<a class="btn ghost fb" href={app.path('/flows')} aria-label={t('a.back')}><Icon name="back" size={16} /></a>
	<input class="in" bind:value={meta.name} oninput={() => (dirty = true)} aria-label={t('devs.name')} disabled={!admin} />
	<select class="in fm" bind:value={meta.mode} onchange={() => (dirty = true)} aria-label={t('flows.mode')} disabled={!admin}>
		{#each ['single', 'restart', 'queued', 'parallel'] as m}<option value={m}>{t(`mode.${m}`)}</option>{/each}
	</select>
	<label class="fon sm" title={t('fl.enabled')}><Toggle on={meta.enabled} label={t('fl.enabled')} disabled={!admin} onclick={() => ((meta.enabled = !meta.enabled), (dirty = true))} /><span>{t('fl.enabled')}</span></label>
	{#if admin}
		<span class="fh">
			<button class="btn ghost" disabled={!past.length} onclick={undo} title="{t('fl.undo')} (Ctrl+Z)" aria-label={t('fl.undo')}><Icon name="undo" size={16} /></button>
			<button class="btn ghost" disabled={!future.length} onclick={redo} title="{t('fl.redo')} (Ctrl+Shift+Z)" aria-label={t('fl.redo')}><Icon name="redo" size={16} /></button>
		</span>
	{/if}
	{#if flow?.dead?.length}<span class="chip warn">{t('flows.dead')}: {flow.dead.join(', ')}</span>{/if}
	<button class="btn fa" onclick={test} title={t('a.test')} aria-label={t('a.test')}><Icon name="play" size={16} /><span>{t('a.test')}</span></button>
	<button class="btn fa" disabled={!flow?.enabled || dirty} onclick={() => app.run(() => app.api('POST', `/flows/${id}/run`), t('flows.started', { name: meta.name }))} title={t('a.run')} aria-label={t('a.run')}><Icon name="send" size={16} /><span>{t('a.run')}</span></button>
	{#if admin}<button class="btn pri fs" disabled={!dirty || !meta.name.trim()} onclick={save}>{t('a.save')}</button>{/if}
</div>

<div class="fe">
	<div class="pal">
		{#each GROUPS as g}
			<h6>{t(`bk.${g}s`)}</h6>
			{#each Object.values(reg.blocks).filter((b) => b.kind === g) as b (b.key)}
				<button class="pb" disabled={!admin} onclick={() => add(b.key)}><i style="background:{KIND_COLOR[g]}"></i>{blockName(app, b, b.key)}{#if b.ext}<em>{t('fl.ext')}</em>{/if}</button>
			{/each}
		{/each}
	</div>
	<div class="cv">
		<SvelteFlow
			bind:nodes
			bind:edges
			{nodeTypes}
			fitViewOptions={{ minZoom: 0.8, maxZoom: 1, padding: 0.15 }}
			minZoom={0.3}
			nodesDraggable={admin}
			nodesConnectable={admin}
			elementsSelectable={admin}
			deleteKey={admin ? ['Delete', 'Backspace'] : null}
			isValidConnection={valid}
			onconnect={commit}
			ondelete={commit}
			onnodedragstop={commit}
			onnodeclick={({ node: n }) => ((sel = n.id), (side = 'node'))}
			onpaneclick={() => (sel = null)}
			colorMode="system"
			proOptions={{ hideAttribution: true }}
		>
			<Background gap={22} />
			<Controls showLock={false} />
			<FlowFit key={flow?.id ?? ''} />
		</SvelteFlow>
	</div>
	<div class="insp">
		<div class="seg">
			<button class:on={side === 'node'} aria-pressed={!!(side === 'node')} onclick={() => (side = 'node')}>{t('fl.block')}</button>
			<button class:on={side === 'test'} aria-pressed={!!(side === 'test')} onclick={() => (side = 'test')}>{t('fl.check')}</button>
			<button class:on={side === 'runs'} aria-pressed={!!(side === 'runs')} onclick={() => (side = 'runs')}>{t('fl.runs')}</button>
			<button class:on={side === 'versions'} aria-pressed={!!(side === 'versions')} onclick={showVersions}>{t('fl.versions')}</button>
		</div>
		{#if side === 'node'}
			{#if node}
				<div class="row" style="gap:8px"><i style="width:10px;height:10px;border-radius:3px;background:{KIND_COLOR[def?.kind] || 'var(--crit)'}"></i><b>{blockName(app, def, node.data.block)}</b><span class="mono sm dim">{node.id}</span></div>
				{#if !def}<p class="err">{t('fl.dead_hint')}</p>{/if}
				{#each def?.params || [] as p (p.key)}<ParamField {p} params={node.data.params} set={setParam} />{:else}<span class="dim sm">{t('fl.no_params')}</span>{/each}
				{#if admin}
					<div class="row" style="gap:6px;flex-wrap:wrap">
						<button class="btn s" onclick={duplicate} title="Ctrl+D"><Icon name="copy" size={14} />{t('fl.duplicate')}</button>
						<button class="btn s" onclick={copy} title="Ctrl+C"><Icon name="copy" size={14} />{t('a.copy')}</button>
						<button class="btn danger s" onclick={removeNode}><Icon name="trash" size={14} />{t('fl.remove_block')}</button>
					</div>
				{/if}
			{:else}
				<p class="dim sm" style="margin:0">{t('fl.pick_hint')}</p>
				{#if admin}<p class="dim sm kh" style="margin:0">{t('fl.keys_hint')}</p>{/if}
				<dl class="kv">
					<dt>{t('fl.version')}</dt><dd>{flow?.version ?? '-'}</dd>
					<dt>{t('flows.last')}</dt><dd>{flow?.lastResult ? t(`res.${flow.lastResult}`) : t('res.none')}</dd>
					<dt>{t('flows.runs')}</dt><dd>{flow?.runs ?? 0}</dd>
					<dt>{t('fl.updated')}</dt><dd>{flow ? f.stamp(flow.updatedAt) : '-'}</dd>
				</dl>
				{#if admin}<button class="btn danger s" onclick={del}><Icon name="trash" size={14} />{sure ? t('a.confirm_delete') : t('fl.delete')}</button>{/if}
			{/if}
		{:else if side === 'test'}
			{#if result}<div class="row"><span class="chip {result.status === 'ok' ? 'ok' : result.status === 'fail' ? 'crit' : 'amber'}">{t(`res.${result.status}`)}</span><span class="sm dim">{t('fl.dry')}</span></div>{/if}
			{@render traceList(result?.trace)}
		{:else if side === 'runs'}
			{#each rnp.st.items as r (r.id)}
				<details class="card" style="padding:10px">
					<summary class="row" style="cursor:pointer"><span class="chip {r.status === 'ok' ? 'ok' : r.status === 'fail' ? 'crit' : 'amber'}">{t(`res.${r.status}`)}</span><span class="mono sm">{f.stamp(r.startedAt)}</span></summary>
					<div style="margin-top:8px">{@render traceList(r.trace)}</div>
				</details>
			{:else}<span class="dim sm">{t('fl.no_runs')}</span>{/each}
			<More p={rnp} />
		{:else}
			{#each versions as v (v.version)}
				<div class="ri"><b style="font-weight:500">v{v.version}</b><span class="sm dim">{v.author}</span><small>{f.stamp(v.createdAt)}</small>{#if admin && v.version !== flow?.version}<button class="btn s" onclick={() => restore(v.version)}>{t('a.restore')}</button>{/if}</div>
			{:else}<span class="dim sm">-</span>{/each}
		{/if}
	</div>
</div>
