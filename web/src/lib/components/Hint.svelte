<script>
	import { useApp } from '#lib/app.svelte.js';
	import Icon from './Icon.svelte';

	let { k, doc = '', text = '' } = $props();
	const app = useApp();
	const { t } = app;
	const id = `hint-${Math.random().toString(36).slice(2, 9)}`;
	let open = $state(false);
	let pinned = $state(false);
	let btn = $state();
	let tip = $state();
	let pos = $state({ top: 0, left: 0, width: 300 });
	let leave;
	const body = $derived(text || t(`hint.${k}`));

	function place() {
		if (!btn) return;
		const r = btn.getBoundingClientRect();
		const width = Math.min(300, innerWidth - 32);
		const left = Math.min(Math.max(16, r.left + r.width / 2 - width / 2), innerWidth - width - 16);
		const h = tip?.offsetHeight || 0;
		const below = r.bottom + 8;
		pos = { top: h && below + h > innerHeight - 8 && r.top - h - 8 > 8 ? r.top - h - 8 : below, left, width };
	}
	function show() {
		clearTimeout(leave);
		open = true;
		place();
		requestAnimationFrame(place);
	}
	function hide() {
		leave = setTimeout(() => !pinned && (open = false), 150);
	}
	function toggle(e) {
		e.stopPropagation();
		pinned = !pinned || !open;
		if (pinned) show();
		else open = false;
	}
	function close() {
		pinned = false;
		open = false;
	}
	$effect(() => {
		if (!open) return;
		const out = (e) => !btn?.contains(e.target) && !tip?.contains(e.target) && close();
		const key = (e) => e.key === 'Escape' && (close(), btn?.focus());
		addEventListener('pointerdown', out, true);
		addEventListener('keydown', key);
		addEventListener('scroll', close, true);
		addEventListener('resize', close);
		return () => {
			removeEventListener('pointerdown', out, true);
			removeEventListener('keydown', key);
			removeEventListener('scroll', close, true);
			removeEventListener('resize', close);
		};
	});
</script>

<span class="hq" role="presentation" onmouseenter={show} onmouseleave={hide}>
	<button bind:this={btn} type="button" class="hb" aria-label={t('hint.aria')} aria-expanded={open} aria-describedby={open ? id : undefined} onclick={toggle} onfocus={show} onblur={hide}><Icon name="help" size={15} /></button>
	{#if open}
		<span bind:this={tip} {id} role="tooltip" class="tip" style:top="{pos.top}px" style:left="{pos.left}px" style:width="{pos.width}px">
			<span>{body}</span>
			{#if doc}<a href={app.path(`/docs/${doc}`)} onclick={close}>{t('hint.more')}<Icon name="chev" size={12} /></a>{/if}
		</span>
	{/if}
</span>

<style>
	.hq {
		display: inline-flex;
		vertical-align: middle;
	}
	.hb {
		display: inline-grid;
		place-items: center;
		width: 22px;
		height: 22px;
		padding: 0;
		border: 0;
		border-radius: 50%;
		background: none;
		color: var(--ink-3);
	}
	.hb:hover,
	.hb[aria-expanded='true'] {
		color: var(--frost);
		background: color-mix(in srgb, var(--frost) 12%, transparent);
	}
	.tip {
		position: fixed;
		z-index: 60;
		display: grid;
		gap: 8px;
		padding: 11px 13px;
		border-radius: 12px;
		background: var(--panel);
		border: 1px solid var(--line-2);
		box-shadow: var(--shadow);
		color: var(--ink);
		font: 400 13px/1.5 var(--f-d);
		letter-spacing: 0;
		text-transform: none;
		white-space: normal;
		text-align: left;
	}
	.tip a {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		font-weight: 500;
		width: fit-content;
	}
</style>
