<script>
	import { useApp } from '#lib/app.svelte.js';
	import { canWrite, cap } from '#lib/devices.js';
	import Icon from './Icon.svelte';
	import Toggle from './Toggle.svelte';

	let { d } = $props();
	const app = useApp();
	const { s, t, f } = app;
	const pend = $derived(s.cmds[d.id]);
	const spCap = $derived(cap(d, 'sp') || cap(d, 'target'));
	const gangs = $derived(d.caps.filter((c) => /^on_/.test(c.id) && c.access.includes('w')));
	const step = (c, dir) => {
		const v = +(d.state[c.id] ?? 0) + dir * (c.step || 0.5);
		app.cmd(d.id, { [c.id]: Math.min(c.max ?? 99, Math.max(c.min ?? 0, Math.round(v * 10) / 10)) });
	};
</script>

{#if !d.available}
	<span class="chip crit">{t('v.offline')}</span>
{:else if canWrite(d, 'on')}
	<Toggle on={pend?.values.on ?? d.state.on} pending={!!pend} label={d.name} onclick={() => app.cmd(d.id, { on: !d.state.on })} />
{:else if gangs.length}
	<div class="row" style="gap:6px">
		{#each gangs as c (c.id)}<Toggle on={pend?.values[c.id] ?? d.state[c.id]} pending={pend?.values[c.id] != null} label="{d.name} {c.id.slice(3)}" onclick={() => app.cmd(d.id, { [c.id]: !d.state[c.id] })} />{/each}
	</div>
{:else if canWrite(d, 'locked')}
	<button class="btn s" onclick={() => app.cmd(d.id, { locked: !d.state.locked })}><Icon name="lock" size={14} />{d.state.locked ? t('a.unlock') : t('a.lock')}</button>
{:else if spCap && spCap.access.includes('w')}
	<div class="stp">
		<button onclick={() => step(spCap, -1)} aria-label={t('a.lower')}>−</button>
		<b class="num" style="min-width:38px;text-align:center" class:dim={!!pend}>{f.n(pend?.values[spCap.id] ?? d.state[spCap.id], 1)}</b>
		<button onclick={() => step(spCap, 1)} aria-label={t('a.higher')}>+</button>
	</div>
{:else if canWrite(d, 'pos')}
	<div class="row" style="gap:6px">
		<button class="btn s" onclick={() => app.cmd(d.id, { pos: 0 })}>{t('a.close_blind')}</button>
		<button class="btn s" onclick={() => app.cmd(d.id, { pos: 100 })}>{t('a.open_blind')}</button>
	</div>
{/if}
