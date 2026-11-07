<script>
	import { useApp } from '#lib/app.svelte.js';
	import { unit } from '#lib/devices.js';
	import BClock from './BClock.svelte';
	import BHero from './BHero.svelte';
	import BStrip from './BStrip.svelte';
	import Bars from './Bars.svelte';
	import Icon from './Icon.svelte';

	let { blocks = [], compact = false, onaction = null } = $props();
	let busy = $state('');
	async function act(key) {
		if (!onaction || busy) return;
		busy = key;
		try {
			await onaction(key);
		} finally {
			busy = '';
		}
	}
	const app = useApp();
	const { f, t } = app;
	const tx = (x) => (x && typeof x === 'object' ? (x[app.lang] ?? x.en ?? Object.values(x)[0]) : (x ?? ''));
	const num = (v, u, d) => `${f.n(v, d ?? 1)}${u ? `\u00a0${unit(t, String(u).trim())}` : ''}`;
	function part(p) {
		if (!p || typeof p !== 'object' || !('value' in p || 'range' in p || 'text' in p)) return tx(p);
		if (Array.isArray(p.range)) return `${f.n(p.range[0], p.digits ?? 1)} … ${num(p.range[1], p.unit, p.digits)}`;
		if (typeof p.value === 'number') return num(p.value, p.unit, p.digits);
		return tx(p.text ?? p.value);
	}
	const val = (it) => (Array.isArray(it.values) ? it.values.map(part).filter(Boolean).join(', ') : typeof it.value === 'number' ? num(it.value, it.unit, it.digits) : tx(it.value));
	const acts = (it) => [...(it.action ? [it.action] : []), ...(it.actions || [])];
	const auto = (vs) => ((vs || []).every((v) => v == null || Number.isInteger(v)) ? 0 : 1);
</script>

<div class="g" style="gap:14px">
	{#each blocks as b, i (i)}
		{#if b.type === 'clock'}
			<BClock {compact} />
		{:else if b.type === 'hero'}
			<BHero {b} {compact} />
		{:else if b.type === 'strip'}
			<BStrip {b} {compact} />
		{:else if b.type === 'stats'}
			<div class="big" class:cmp={compact}>
				{#each b.items as it}<div class:long={typeof it.value !== 'number' && tx(it.value).length > 14}><span class="lbl">{tx(it.label)}</span><b class:txt={typeof it.value !== 'number'}>{typeof it.value === 'number' ? f.n(it.value, it.digits ?? 1) : tx(it.value) || '-'}<small>{it.unit ? `\u00a0${unit(t, String(it.unit).trim())}` : ''}</small></b></div>{/each}
			</div>
		{:else if b.type === 'bars'}
			<div>
				{#if !compact}<div class="lbl" style="margin-bottom:8px">{tx(b.label)}</div>{/if}
				<Bars
					values={b.values || []}
					now={b.now ?? -1}
					marks={b.marks || []}
					height={compact ? 56 : 120}
					label={tx(b.label)}
					labels={b.labels || []}
					unit={unit(t, String(b.unit || '').trim())}
					digits={b.digits ?? auto(b.values)}
					series={(b.series || []).map((s) => ({ ...s, label: tx(s.label) }))}
					kinds={b.kinds || []}
					axis={!compact}
				/>
			</div>
		{:else if b.type === 'list'}
			<div class="bl">
				<div class="lbl" style="margin-bottom:8px">{tx(b.label)}</div>
				<div class="lst">
					{#each b.items as it}
						<div class="ri">
							<span class="btx">{tx(it.text)}</span>{#if val(it)}<small class="rv">{val(it)}</small>{/if}
							{#each acts(it) as a (a.key)}
								<button class="btn s" class:pri={a.primary} title={compact ? tx(a.label) : undefined} disabled={!onaction || !!busy} onclick={() => act(a.key)}
									>{#if a.icon}<Icon name={a.icon} size={14} />{/if}{#if busy === a.key}...{:else if compact && a.icon}<span class="vis">{tx(a.label)}</span>{:else}{tx(a.label)}{/if}{#if a.hint}<span class="vis">{` ${tx(a.hint)}`}</span>{/if}</button
								>
							{/each}
						</div>
					{/each}
				</div>
			</div>
		{:else if b.type === 'actions'}
			<div class="row" style="flex-wrap:wrap;gap:8px">
				{#each b.items as it (it.key)}<button class="btn {it.primary ? 'pri' : ''}" disabled={!onaction || !!busy} onclick={() => act(it.key)}>{#if it.icon}<Icon name={it.icon} size={16} />{/if}{busy === it.key ? '...' : tx(it.label)}</button>{/each}
			</div>
		{:else if b.type === 'text'}
			<p class="dim" style="margin:0">{tx(b.text)}</p>
		{/if}
	{/each}
</div>

<style>
	.bl {
		container-type: inline-size;
	}
	.btx {
		flex: 1;
		min-width: 0;
	}
	@container (max-width: 460px) {
		.bl :global(.ri) {
			flex-wrap: wrap;
			row-gap: 2px;
		}
		.rv {
			order: 2;
			flex-basis: 100%;
			text-align: left;
		}
	}
</style>
