<script>
	import { useApp } from '#lib/app.svelte.js';
	import { capName } from '#lib/devices.js';

	let { p, params, set } = $props();
	const app = useApp();
	const { s, t } = app;
	const v = $derived(params[p.key]);
	const dev = $derived(s.devices[params.device]);
	const caps = $derived(dev?.caps ?? []);
	const capObj = $derived(caps.find((c) => c.id === params.cap));
	const label = $derived(t.has(`prm.${p.key}`) ? t(`prm.${p.key}`) : p.key);
	const devs = $derived(Object.values(s.devices).sort((a, b) => a.name.localeCompare(b.name)));
	const parse = (x, c) => (c?.type === 'num' ? (x === '' ? null : +x) : c?.type === 'bool' ? x === 'true' : x);
	const opt = (x) => (t.has(`opt.${x}`) ? t(`opt.${x}`) : x);
	let vk = $state('');
</script>

{#snippet scalar(cur, c, onset, aria)}
	{#if c?.type === 'bool'}
		<select class="in" value={String(cur ?? '')} aria-label={aria} onchange={(e) => onset(e.target.value === '' ? null : e.target.value === 'true')}>
			<option value="">-</option><option value="true">{t('v.yes')}</option><option value="false">{t('v.no')}</option>
		</select>
	{:else if c?.type === 'enum'}
		<select class="in" value={cur ?? ''} aria-label={aria} onchange={(e) => onset(e.target.value)}><option value="">-</option>{#each c.values || [] as x}<option value={x}>{x}</option>{/each}</select>
	{:else}
		<input class="in" type={c?.type === 'num' ? 'number' : 'text'} step="any" value={cur ?? ''} aria-label={aria} onchange={(e) => onset(parse(e.target.value, c))} />
	{/if}
{/snippet}

<label class="f">
	<span>{label}{#if p.required === false} <span class="sm" style="color:var(--ink-3)">{t('fl.optional')}</span>{/if}</span>
	{#if p.type === 'device'}
		<select class="in" value={v ?? ''} onchange={(e) => set(p.key, e.target.value)}><option value="">-</option>{#each devs as d (d.id)}<option value={d.id}>{d.name}</option>{/each}</select>
	{:else if p.type === 'camera'}
		<select class="in" value={v ?? ''} onchange={(e) => set(p.key, e.target.value)}><option value="">{p.required === false ? t('fl.camera_from_event') : '-'}</option>{#each devs.filter((d) => d.kind === 'camera') as d (d.id)}<option value={d.id}>{d.name}</option>{/each}</select>
	{:else if p.type === 'cap'}
		{#if caps.length}
			<select class="in" value={v ?? ''} onchange={(e) => set(p.key, e.target.value)}><option value="">-</option>{#each caps as c (c.id)}<option value={c.id}>{capName(t, c)}</option>{/each}</select>
		{:else}<input class="in" value={v ?? ''} onchange={(e) => set(p.key, e.target.value)} />{/if}
	{:else if p.type === 'value'}
		{@render scalar(v, capObj, (x) => set(p.key, x), label)}
	{:else if p.type === 'number'}
		<input class="in" type="number" step="any" value={v ?? ''} onchange={(e) => set(p.key, e.target.value === '' ? null : +e.target.value)} />
	{:else if p.type === 'duration'}
		<div class="row" style="flex-wrap:nowrap"><input class="in" type="number" min="0" value={v ?? ''} onchange={(e) => set(p.key, +e.target.value)} /><span class="sm dim">{t('d.sec')}</span></div>
	{:else if p.type === 'time'}
		<input class="in" type="time" value={v ?? ''} onchange={(e) => set(p.key, e.target.value)} />
	{:else if p.type === 'select'}
		<select class="in" value={v ?? ''} onchange={(e) => set(p.key, e.target.value)}><option value="">-</option>{#each p.options || [] as o}<option value={o}>{opt(o)}</option>{/each}</select>
	{:else if p.type === 'bool'}
		<input type="checkbox" checked={!!v} onchange={(e) => set(p.key, e.target.checked)} />
	{:else if p.type === 'scene'}
		<select class="in" value={v ?? ''} onchange={(e) => set(p.key, e.target.value)}><option value="">-</option>{#each s.scenes as x (x.id)}<option value={x.id}>{x.name}</option>{/each}</select>
	{:else if p.type === 'days'}
		<div class="seg">{#each [1, 2, 3, 4, 5, 6, 7] as d}<button type="button" class:on={(v || []).includes(d)} aria-pressed={!!((v || []).includes(d))} onclick={() => set(p.key, (v || []).includes(d) ? v.filter((x) => x !== d) : [...(v || []), d].sort())}>{t(`wd.${d}`)}</button>{/each}</div>
	{:else if p.type === 'list'}
		<input class="in" value={(v || []).join(', ')} onchange={(e) => set(p.key, e.target.value.split(',').map((x) => x.trim()).filter(Boolean))} />
	{:else if p.type === 'values'}
		<div class="g" style="gap:6px">
			{#each Object.entries(v || {}) as [k, x] (k)}
				{@const c = caps.find((y) => y.id === k)}
				<div class="row" style="flex-wrap:nowrap;gap:6px">
					<span class="sm" style="min-width:90px">{c ? capName(t, c) : k}</span>
					{@render scalar(x, c, (y) => set(p.key, { ...v, [k]: y }), k)}
					<button type="button" class="ib" style="width:30px;height:30px" aria-label={t('a.delete')} onclick={() => set(p.key, Object.fromEntries(Object.entries(v).filter(([y]) => y !== k)))}>×</button>
				</div>
			{/each}
			<select class="in" bind:value={vk} onchange={() => vk && (set(p.key, { ...(v || {}), [vk]: caps.find((c) => c.id === vk)?.type === 'bool' ? true : (dev?.state[vk] ?? '') }), (vk = ''))}>
				<option value="">{t('fl.add_value')}</option>
				{#each caps.filter((c) => c.access.includes('w') && !(c.id in (v || {}))) as c (c.id)}<option value={c.id}>{capName(t, c)}</option>{/each}
			</select>
		</div>
	{:else}
		<input class="in" value={v ?? ''} onchange={(e) => set(p.key, e.target.value)} />
	{/if}
</label>
