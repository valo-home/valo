<script>
	import { getContext } from 'svelte';
	import { Handle, Position } from '@xyflow/svelte';
	import { useApp } from '#lib/app.svelte.js';
	import { KIND_COLOR, PORT_COLOR, blockName, summary } from '#lib/flowtext.js';

	let { data, selected } = $props();
	const app = useApp();
	const reg = getContext('flowreg');
	const def = $derived(reg.blocks[data.block]);
	const ins = $derived(def?.ins ?? ['ev']);
	const outs = $derived(def?.outs ?? ['ev']);
	const top = (i, n) => `${n === 1 ? 50 : 30 + (i * 40) / Math.max(1, n - 1)}%`;
</script>

<div class="nd" class:sel={selected} class:dead={!def} class:ok={data.st === 'ok'} class:fail={data.st === 'fail'}>
	<div class="ndh">
		<i style="width:8px;height:8px;border-radius:2px;flex:none;background:{KIND_COLOR[def?.kind] || 'var(--crit)'}"></i>
		<span>{blockName(app, def, data.block)}</span>
		<span class="k" style="color:{KIND_COLOR[def?.kind] || 'var(--crit)'}">{app.t(`bk.${def?.kind || 'dead'}`)}</span>
	</div>
	<div class="ndb">
		{summary(app, data.block, data.params) || app.t('fl.no_params')}
		{#if def?.ext}<div class="xb">{def.ext}</div>{:else if !def}<div class="xb" style="color:var(--crit)">{app.t('fl.dead_block')}</div>{/if}
		{#if outs.length > 1}{#each def?.labels ?? [] as l, i}<span class="pl" style="top:{top(i, outs.length)}">{app.t(`port.${l}`)}</span>{/each}{/if}
	</div>
	{#each ins as p, i}<Handle type="target" position={Position.Left} id="i{i}" style="top:{top(i, ins.length)};background:{PORT_COLOR[p] || PORT_COLOR.ev}" />{/each}
	{#each outs as p, i}<Handle type="source" position={Position.Right} id="o{i}" style="top:{top(i, outs.length)};background:{PORT_COLOR[p] || PORT_COLOR.ev}" />{/each}
</div>
