<script>
	import { keepTab } from '#lib/tabs.js';
	import Pages from '#lib/components/Pages.svelte';
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { useApp } from '#lib/app.svelte.js';
	import { values } from '#lib/flowtext.js';
	import Icon from '#lib/components/Icon.svelte';
	import Hint from '#lib/components/Hint.svelte';
	import Modal from '#lib/components/Modal.svelte';
	import Toggle from '#lib/components/Toggle.svelte';

	const app = useApp();
	const { s, t, f } = app;
	const ICONS = ['sun', 'moon', 'play', 'shield', 'blind', 'layers', 'bulb', 'heat', 'home', 'flame'];
	let tab = $state(page.url.searchParams.get('tab') || 'flows');
	$effect(() => keepTab(tab, 'flows'));
	let tpls = $state([]);
	let mk = $state();
	let nf = $state({ name: '', tpl: '' });
	let sc = $state();
	let form = $state({ name: '', icon: 'layers', devices: [] });
	let sure = $state(false);
	const res = (x) => ({ ok: 'ok', fail: 'crit', wait: 'amber', run: 'amber', stop: '' })[x] ?? '';
	const writable = (d) => d.caps.filter((c) => c.access.includes('w') && d.state[c.id] != null);
	const devs = $derived(Object.values(s.devices).filter((d) => writable(d).length).sort((a, b) => a.name.localeCompare(b.name)));

	onMount(() => app.api('GET', '/flows/templates').then((x) => (tpls = x)).catch((e) => console.warn('flow templates failed', e?.message)));

	const tplName = (x) => (t.has(`tpl.${x.key}`) ? t(`tpl.${x.key}`) : x.name && typeof x.name === 'object' ? (x.name[app.lang] ?? x.name.en ?? Object.values(x.name)[0]) : x.name || x.key);
	async function create() {
		const tp = tpls.find((x) => x.key === nf.tpl);
		const r = await app.run(() => app.api('POST', '/flows', { name: nf.name.trim(), mode: 'single', enabled: false, graph: tp?.graph || { nodes: [], edges: [] } }));
		if (r) (mk.hide(), goto(app.path(`/flows/${r.id}`)));
	}
	const toggle = (x) => app.run(() => app.api('PATCH', `/flows/${x.id}`, { enabled: !x.enabled }));
	const run = (x) => app.run(() => app.api('POST', `/flows/${x.id}/run`), t('flows.started', { name: x.name }));
	function editScene(x) {
		form = x ? { id: x.id, name: x.name, icon: x.icon, devices: Object.keys(x.actions), actions: x.actions } : { name: '', icon: 'layers', devices: [], actions: {} };
		sure = false;
		sc.show();
	}
	async function saveScene() {
		const actions = Object.fromEntries(
			form.devices.map((id) => [id, form.actions[id] ?? Object.fromEntries(writable(s.devices[id]).map((c) => [c.id, s.devices[id].state[c.id]]))])
		);
		const body = { name: form.name.trim(), icon: form.icon, actions };
		if (await app.run(() => (form.id ? app.api('PATCH', `/scenes/${form.id}`, body) : app.api('POST', '/scenes', body)), t('scenes.saved'))) sc.hide();
	}
	async function delScene() {
		if (!sure) return void (sure = true);
		if (await app.run(() => app.api('DELETE', `/scenes/${form.id}`), t('scenes.deleted'))) sc.hide();
	}
	const SIZE = 50;
	let pg = $state(0);
	const sorted = $derived([...s.flows].sort((a, b) => a.name.localeCompare(b.name)));
</script>

<svelte:head><title>{t('nav.flows')} · valo</title></svelte:head>

<div class="ph">
	<div><h1>{t('nav.flows')}</h1><p>{tab === 'scenes' ? t('scenes.sub') : t('flows.sub')}</p></div>
	{#if app.can('admin')}
		{#if tab === 'flows'}<button class="btn pri" onclick={() => ((nf = { name: '', tpl: '' }), mk.show())}><Icon name="plus" size={16} />{t('flows.new')}</button>
		{:else}<button class="btn pri" onclick={() => editScene(null)}><Icon name="plus" size={16} />{t('scenes.new')}</button>{/if}
	{/if}
</div>
<div class="tabs">
	<span class="th"><button class:on={tab === 'flows'} onclick={() => (tab = 'flows')}>{t('flows.t_flows')}</button><Hint k="flows" doc="flows" /></span>
	<span class="th"><button class:on={tab === 'scenes'} onclick={() => (tab = 'scenes')}>{t('flows.t_scenes')}</button><Hint k="scenes" doc="scenes" /></span>
</div>

{#if tab === 'flows'}
	<div class="tw">
		<table class="t-flows">
			<thead><tr><th></th><th>{t('devs.name')}</th><th>{t('flows.mode')} <Hint k="flow_mode" doc="flows" /></th><th>{t('flows.last')} <Hint k="flow_result" doc="flows" /></th><th>{t('flows.runs')}</th><th></th></tr></thead>
			<tbody>
				{#each sorted.slice(pg * SIZE, (pg + 1) * SIZE) as x (x.id)}
					<tr>
						<td style="width:56px"><Toggle on={x.enabled} label={x.name} disabled={!app.can('admin')} onclick={() => toggle(x)} /></td>
						<td>
							<a class="dn" href={app.path(`/flows/${x.id}`)}>{x.name}</a>
							{#if x.dead?.length}<span class="chip warn" title={x.dead.join(', ')}>{t('flows.dead')}</span>{/if}
						</td>
						<td class="dim sm">{t(`mode.${x.mode}`)}</td>
						<td>{#if x.lastResult}<span class="chip {res(x.lastResult)}">{t(`res.${x.lastResult}`)}</span> <span class="dim sm">{f.ago(x.lastRunAt)}</span>{:else}<span class="dim sm">{t('res.none')}</span>{/if}</td>
						<td class="num dim">{x.runs}</td>
						<td style="text-align:right"><button class="btn s" disabled={!x.enabled || x.dead?.length} onclick={() => run(x)}><Icon name="play" size={14} />{t('a.run')}</button></td>
					</tr>
				{:else}<tr><td colspan="6" class="dim">{t('flows.none')}</td></tr>{/each}
			</tbody>
		</table>
	</div>
	<Pages total={sorted.length} size={SIZE} bind:page={pg} />
	{#if s.runs && Object.keys(s.runs).length}
		<p class="sm dim">{t('flows.today', { ok: s.runs.ok ?? 0, fail: s.runs.fail ?? 0, wait: s.runs.wait ?? 0 })}</p>
	{/if}
{:else}
	<div class="wg">
		{#each s.scenes as x (x.id)}
			<section class="card g" style="gap:10px;grid-template-rows:auto 1fr auto">
				<h3><Icon name={x.icon} size={16} />{x.name}<span class="sp"></span>{#if app.can('admin')}<button class="btn s ghost" onclick={() => editScene(x)}>{t('a.edit')}</button>{/if}</h3>
				<div class="sm dim">{Object.entries(x.actions).map(([id, v]) => `${s.devices[id]?.name ?? id}: ${values(app, id, v)}`).join('; ') || t('scenes.empty')}</div>
				<div class="row">
					<button class="btn s pri" onclick={() => app.run(() => app.api('POST', `/scenes/${x.id}/apply`), t('scenes.applied', { name: x.name }))}><Icon name="play" size={14} />{t('a.apply')}</button>
					{#if app.can('admin')}<span class="fl"><button class="btn s ghost" style="min-width:0" title={t('scenes.capture')} onclick={() => app.run(() => app.api('POST', `/scenes/${x.id}/capture`), t('scenes.captured'))}><Icon name="download" size={14} /><span style="overflow:hidden;text-overflow:ellipsis">{t('scenes.capture')}</span></button><Hint k="scene_capture" doc="scenes" /></span>{/if}
				</div>
			</section>
		{:else}<div class="empty">{t('home.no_scenes')}</div>{/each}
	</div>
{/if}

<Modal bind:this={mk} title={t('flows.new')}>
	<label class="f">{t('devs.name')}<input class="in" bind:value={nf.name} /></label>
	<div class="lbl">{t('flows.template')} <Hint k="flow_tpl" doc="flows" /></div>
	<div class="lst">
		<button class="opt" class:on={!nf.tpl} onclick={() => (nf.tpl = '')}><span class="dico"><Icon name="plus" size={16} /></span><span>{t('flows.blank')}</span></button>
		{#each tpls as x (x.key)}<button class="opt" class:on={nf.tpl === x.key} onclick={() => ((nf.tpl = x.key), !nf.name && (nf.name = tplName(x)))}><span class="dico"><Icon name={x.ext ? 'ext' : 'flow'} size={16} /></span><span>{tplName(x)}{#if x.ext}<small class="dim" style="display:block">{x.ext}</small>{/if}</span></button>{/each}
	</div>
	{#snippet foot()}
		<button class="btn" onclick={() => mk.hide()}>{t('a.cancel')}</button>
		<button class="btn pri" disabled={!nf.name.trim()} onclick={create}>{t('a.create')}</button>
	{/snippet}
</Modal>

<Modal bind:this={sc} title={form.id ? t('scenes.edit') : t('scenes.new')} wide>
	<div class="fg">
		<label class="f">{t('devs.name')}<input class="in" bind:value={form.name} /></label>
		<div class="f">{t('scenes.icon')}<div class="seg" style="flex-wrap:wrap">{#each ICONS as i}<button class:on={form.icon === i} aria-pressed={!!(form.icon === i)} aria-label={i} onclick={() => (form.icon = i)}><Icon name={i} size={16} /></button>{/each}</div></div>
	</div>
	<div class="lbl">{t('scenes.devices')}</div>
	<div class="lst" style="max-height:320px;overflow:auto">
		{#each devs as d (d.id)}
			<label class="ri"><input type="checkbox" value={d.id} bind:group={form.devices} /><span style="flex:1">{d.name}</span><small>{form.actions[d.id] ? values(app, d.id, form.actions[d.id]) : t('scenes.current')}</small></label>
		{/each}
	</div>
	{#if form.id}<div><button class="btn danger" onclick={delScene}><Icon name="trash" size={16} />{sure ? t('a.confirm_delete') : t('a.delete')}</button></div>{/if}
	{#snippet foot()}
		<button class="btn" onclick={() => sc.hide()}>{t('a.cancel')}</button>
		<button class="btn pri" disabled={!form.name.trim() || !form.devices.length} onclick={saveScene}>{t('a.save')}</button>
	{/snippet}
</Modal>
