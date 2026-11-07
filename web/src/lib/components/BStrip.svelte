<script>
	import { useApp } from '#lib/app.svelte.js';
	import { unit } from '#lib/devices.js';
	import Icon from './Icon.svelte';

	let { b, compact = false } = $props();
	const app = useApp();
	const { f, t } = app;
	const TONES = ['amber', 'frost', 'violet', 'ok', 'warn', 'crit'];
	const tx = (x) => (x && typeof x === 'object' ? (x[app.lang] ?? x.en ?? Object.values(x)[0]) : (x ?? ''));
	const tone = (x) => (TONES.includes(x) ? `var(--${x})` : 'var(--ink-2)');
	const val = (it) => (typeof it.value === 'number' ? `${f.n(Math.round(it.value * 10 ** (it.digits ?? 0)) / 10 ** (it.digits ?? 0) || 0, it.digits ?? 0)}${it.unit ? (String(it.unit).trim().startsWith('°') ? '' : '\u00a0') + unit(t, String(it.unit).trim()) : ''}` : tx(it.value) || '-');
</script>

<div class="strip-w">
	{#if b.label && !compact}<div class="lbl" style="margin-bottom:8px">{tx(b.label)}</div>{/if}
	<ol class="strip" aria-label={tx(b.label)}>
		{#each b.items || [] as it, i}
			<li class:now={i === (b.now ?? -1)}>
				<span class="h">{tx(it.label)}</span>
				{#if it.icon}<span style:color={tone(it.tone)}><Icon name={it.icon} size={22} /></span>{/if}
				<b class="num">{val(it)}</b>
				{#if it.sub}<span class="s num">{tx(it.sub)}</span>{/if}
			</li>
		{/each}
	</ol>
</div>

<style>
	.strip {
		list-style: none;
		margin: 0;
		padding: 0 0 2px;
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(46px, 1fr));
		grid-template-rows: auto;
		grid-auto-rows: 0;
		column-gap: 4px;
		row-gap: 0;
		overflow: hidden;
	}
	.strip-w {
		min-width: 0;
	}
	li {
		display: grid;
		justify-items: center;
		gap: 5px;
		padding: 8px 2px;
		border-radius: 12px;
	}
	li.now {
		background: var(--raise);
		box-shadow: inset 0 0 0 1px var(--line);
	}
	.h {
		font: 500 11px var(--f-m);
		color: var(--ink-3);
		white-space: nowrap;
	}
	li.now .h {
		color: var(--ink);
	}
	b {
		font-size: 14px;
		font-weight: 600;
	}
	.s {
		font-size: 11px;
		color: var(--frost);
		min-height: 1em;
	}
</style>
