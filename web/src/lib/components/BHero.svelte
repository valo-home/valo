<script>
	import { useApp } from '#lib/app.svelte.js';
	import { unit } from '#lib/devices.js';
	import Icon from './Icon.svelte';

	let { b, compact = false } = $props();
	const app = useApp();
	const { f, t } = app;
	const TONES = ['amber', 'frost', 'violet', 'ok', 'warn', 'crit'];
	const tx = (x) => (x && typeof x === 'object' ? (x[app.lang] ?? x.en ?? Object.values(x)[0]) : (x ?? ''));
	const u = (x) => (x ? unit(t, String(x).trim()) : '');
	const su = (x) => (!x ? '' : String(x).trim().startsWith('°') ? u(x) : `\u00a0${u(x)}`);
	const n = (v, d) => (typeof v === 'number' ? f.n(Math.round(v * 10 ** (d ?? 1)) / 10 ** (d ?? 1) || 0, d ?? 1) : '-');
	const part = (p) => {
		if (!p || typeof p !== 'object' || !('value' in p || 'range' in p)) return tx(p);
		const v = Array.isArray(p.range) ? `${n(p.range[0], p.digits)}${su(p.unit)} … ${n(p.range[1], p.digits)}${su(p.unit)}` : `${n(p.value, p.digits)}${su(p.unit)}`;
		return p.label ? `${tx(p.label)} ${v}` : v;
	};
	const sub = $derived((Array.isArray(b.sub) ? b.sub : b.sub ? [b.sub] : []).map(part).filter(Boolean).join(' · '));
	const tone = $derived(TONES.includes(b.tone) ? `var(--${b.tone})` : 'var(--ink-2)');
</script>

<div class="hc"><div class="hero" class:cmp={compact}>
	<div class="top">
		{#if b.icon}<span class="ico" style:color={tone} style:background="color-mix(in srgb, {tone} 14%, transparent)"><Icon name={b.icon} size={compact ? 34 : 42} /></span>{/if}
		<div class="main">
			{#if b.value != null}<b class="v num">{n(b.value, b.digits)}<small>{u(b.unit)}</small></b>{/if}
			{#if b.text}<span class="tx" class:lead={b.value == null}>{tx(b.text)}</span>{/if}
			{#if sub}<span class="hs">{sub}</span>{/if}
		</div>
	</div>
	{#if b.items?.length}
		<div class="chips">
			{#each b.items as it}
				<span class="hi" title={tx(it.label)}>
					{#if it.icon}<Icon name={it.icon} size={15} />{/if}
					<span class:vis={compact}>{tx(it.label)}</span>
					<b class="num">{typeof it.value === 'number' ? n(it.value, it.digits) : tx(it.value) || '-'}</b>{#if it.unit}<small>{u(it.unit)}</small>{/if}
				</span>
			{/each}
		</div>
	{/if}
</div></div>

<style>
	.hc {
		min-width: 0;
		container-type: inline-size;
	}
	.hero {
		display: grid;
		gap: 14px;
		min-width: 0;
	}
	@container (min-width: 460px) {
		.hero {
			grid-template-columns: minmax(0, 1fr) auto;
			align-items: center;
		}
		.chips {
			justify-content: flex-end;
			max-width: 280px;
		}
	}
	.top {
		display: flex;
		align-items: center;
		gap: 16px;
		min-width: 0;
	}
	.ico {
		display: grid;
		place-items: center;
		width: 72px;
		height: 72px;
		border-radius: 20px;
		flex: none;
	}
	.cmp .ico {
		width: 60px;
		height: 60px;
		border-radius: 17px;
	}
	.main {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}
	.v {
		font: 300 46px/1 var(--f-d);
		letter-spacing: -0.03em;
	}
	.cmp .v {
		font-size: 40px;
	}
	.v small {
		font-size: 18px;
		font-weight: 400;
		color: var(--ink-2);
		margin-left: 3px;
		vertical-align: top;
		letter-spacing: 0;
	}
	.tx {
		font-size: 15px;
		font-weight: 500;
		overflow-wrap: break-word;
	}
	.tx.lead {
		font: 400 24px/1.2 var(--f-d);
		letter-spacing: -0.01em;
	}
	.cmp .tx.lead {
		font-size: 21px;
	}
	.tx::first-letter {
		text-transform: uppercase;
	}
	.hs {
		font-size: 12.5px;
		color: var(--ink-2);
	}
	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.hi {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 5px 10px;
		border-radius: 999px;
		background: var(--raise);
		border: 1px solid var(--line);
		color: var(--ink-2);
		font-size: 12.5px;
	}
	.hi b {
		color: var(--ink);
		font-weight: 500;
	}
	.hi small {
		margin-left: -3px;
	}
</style>
