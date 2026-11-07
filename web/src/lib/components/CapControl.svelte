<script>
	import { useApp } from '#lib/app.svelte.js';
	import { capName, unit, value } from '#lib/devices.js';
	import Toggle from './Toggle.svelte';

	let { d, c } = $props();
	const app = useApp();
	const { s, t, f } = app;
	const pend = $derived(s.cmds[d.id]?.values?.[c.id]);
	const cur = $derived(pend ?? d.state[c.id]);
	let draft = $state(null);
	const send = (v) => app.cmd(d.id, { [c.id]: v });
	const w = $derived(c.access.includes('w') && d.available);
</script>

<div class="row" style="justify-content:space-between;gap:8px 12px;min-height:36px">
	<span class="dim" style="flex:1 1 120px;min-width:0">{capName(t, c)}</span>
	{#if !w}
		<b class="num" style="font-weight:500">{value(app, d, c.id)}</b>
	{:else if c.type === 'bool'}
		<Toggle on={!!cur} pending={pend != null} label={capName(t, c)} onclick={() => send(!d.state[c.id])} />
	{:else if c.type === 'num'}
		<div class="row" style="flex:2 1 220px;max-width:380px;flex-wrap:nowrap">
			{#if c.min != null && c.max != null}
				<input type="range" min={c.min} max={c.max} step={c.step || 1} value={draft ?? cur ?? c.min} aria-label={capName(t, c)} oninput={(e) => (draft = +e.target.value)} onchange={(e) => (send(+e.target.value), (draft = null))} />
			{:else}
				<input class="in" type="number" step={c.step || 'any'} value={cur ?? ''} aria-label={capName(t, c)} onchange={(e) => send(+e.target.value)} />
			{/if}
			<b class="num" style="min-width:64px;text-align:right;font-weight:500">{f.n(draft ?? cur, c.step && c.step < 1 ? 1 : 0)}{c.unit ? `\u00a0${unit(t, c.unit)}` : ''}</b>
		</div>
	{:else if c.type === 'color'}
		<label class="row" style="gap:8px">
			<input type="color" value={cur || '#ffffff'} aria-label={capName(t, c)} onchange={(e) => send(e.target.value)} style="width:44px;height:30px;border:1px solid var(--line-2);border-radius:8px;background:none;padding:2px" />
			<span class="mono sm dim">{cur || '-'}</span>
		</label>
	{:else if c.type === 'enum' && !c.access.includes('r')}
		<div class="row" style="gap:6px;flex-wrap:wrap">{#each c.values || [] as v}<button class="btn s" onclick={() => send(v)}>{t.has(`ev.${v}`) ? t(`ev.${v}`) : v}</button>{/each}</div>
	{:else if c.type === 'enum'}
		<div class="seg">{#each c.values || [] as v}<button class:on={cur === v} aria-pressed={!!(cur === v)} onclick={() => send(v)}>{t.has(`ev.${v}`) ? t(`ev.${v}`) : v}</button>{/each}</div>
	{:else}
		<input class="in" style="max-width:240px" value={cur ?? ''} aria-label={capName(t, c)} onchange={(e) => send(e.target.value)} />
	{/if}
</div>
