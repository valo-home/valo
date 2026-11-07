<script>
	import { useApp } from '#lib/app.svelte.js';
	import { icon, lowBat, primary } from '#lib/devices.js';
	import Icon from './Icon.svelte';

	let { type } = $props();
	const app = useApp();
	const { s, t, f } = app;
	const devs = $derived(Object.values(s.devices).filter((d) => !d.disabled));
	const link = (d) => app.path(`/devices/${encodeURIComponent(d.id)}`);
	const battery = $derived(devs.filter((d) => typeof d.state.bat === 'number').sort((a, b) => a.state.bat - b.state.bat));
	const power = $derived(devs.filter((d) => d.source !== 'ext' && typeof d.state.w === 'number').sort((a, b) => b.state.w - a.state.w));
	const top = $derived(Math.max(1, ...power.map((d) => d.state.w)));
	const total = $derived(power.filter((d) => d.kind !== 'meter').reduce((a, d) => a + d.state.w, 0));
	const attention = $derived([
		...devs.filter((d) => d.state.leak).map((d) => ['crit', 'drop', t('home.leak', { name: d.name }), d]),
		...devs.filter((d) => d.state.smoke).map((d) => ['crit', 'flame', t('home.smoke', { name: d.name }), d]),
		...devs.filter((d) => d.state.co || d.state.gas).map((d) => ['crit', 'warn', t(d.state.co ? 'home.co' : 'home.gas', { name: d.name }), d]),
		...devs.filter((d) => !d.available).map((d) => ['crit', 'warn', t('home.offline', { name: d.name }), d]),
		...devs.filter((d) => d.kind === 'contact' && d.state.open).map((d) => ['warn', 'door', t('home.open', { name: d.name }), d]),
		...devs.filter(lowBat).map((d) => ['warn', 'drop', t('home.battery', { name: d.name, n: d.state.bat }), d])
	]);
</script>

{#if type === 'battery'}
	<div class="lst">
		{#each battery.slice(0, 8) as d (d.id)}
			<a class="ri wbar" href={link(d)}>
				<span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{d.name}</span>
				<span class="meter" class:low={lowBat(d)}><i style="width:{Math.max(4, d.state.bat)}%"></i></span>
				<b class="num" class:crit={lowBat(d)} style="width:42px;text-align:right;font-weight:500">{d.state.bat}%</b>
			</a>
		{:else}<span class="dim sm">{t('w.no_bat')}</span>{/each}
	</div>
{:else if type === 'power'}
	<div class="row" style="justify-content:space-between;align-items:baseline">
		<b class="num wbig">{f.n(total, 0)}<small>{t('u.W')}</small></b><span class="sm dim">{t('w.total')}</span>
	</div>
	<div class="lst">
		{#each power.slice(0, 8) as d (d.id)}
			<a class="ri wbar" href={link(d)}>
				<span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{d.name}</span>
				<span class="meter"><i style="width:{Math.max(2, (d.state.w / top) * 100)}%"></i></span>
				<b class="num" style="width:72px;text-align:right;font-weight:500">{f.n(d.state.w, 0)} {t('u.W')}</b>
			</a>
		{:else}<span class="dim sm">{t('w.no_power')}</span>{/each}
	</div>
{:else if type === 'attention'}
	<div class="lst">
		{#each attention.slice(0, 8) as [lvl, ic, text, d] (text)}
			<a class="ri" href={link(d)}><span style="color:var(--{lvl === 'crit' ? 'crit' : 'amber'});display:flex"><Icon name={ic} size={16} /></span><span style="flex:1;min-width:0">{text}</span></a>
		{:else}<div class="row"><span class="chip ok">{t('w.all_ok')}</span></div>{/each}
	</div>
{:else}
	<div class="lst">
		{#each devs.filter((x) => x.kind === (type === 'leaks' ? 'leak' : 'contact')) as x (x.id)}
			<a class="ri" href={link(x)}><Icon name={icon(x)} size={16} /><span style="flex:1">{x.name}</span><span class="chip {!x.available || x.state.leak ? 'crit' : x.state.open ? 'warn' : 'ok'}">{primary(app, x)}</span></a>
		{:else}<span class="dim sm">{t('w.empty')}</span>{/each}
	</div>
{/if}
