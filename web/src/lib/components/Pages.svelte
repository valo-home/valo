<script>
	import { useApp } from '#lib/app.svelte.js';
	import Icon from './Icon.svelte';

	let { total = 0, size = 50, page = $bindable(0) } = $props();
	const { t } = useApp();
	const count = $derived(Math.max(1, Math.ceil(total / size)));
	const nums = $derived.by(() => {
		const out = [];
		for (let i = 0; i < count; i++) if (i === 0 || i === count - 1 || Math.abs(i - page) <= 1) out.push(i);
		return out.flatMap((n, i) => (i && n - out[i - 1] > 1 ? [-1, n] : [n]));
	});
	$effect(() => {
		if (page > count - 1) page = count - 1;
	});
</script>

{#if total > size}
	<nav class="pages" aria-label={t('pg.nav')}>
		<span class="sm dim">{t('pg.shown', { a: page * size + 1, b: Math.min(total, (page + 1) * size), n: total })}</span>
		<span class="sp"></span>
		<button class="btn s" disabled={page === 0} onclick={() => (page -= 1)} aria-label={t('pg.prev')}><Icon name="back" size={14} /></button>
		{#each nums as n, i (i)}
			{#if n < 0}<span class="dim">…</span>{:else}<button class="btn s" class:pri={n === page} aria-current={n === page ? 'page' : undefined} onclick={() => (page = n)}>{n + 1}</button>{/if}
		{/each}
		<button class="btn s" disabled={page >= count - 1} onclick={() => (page += 1)} aria-label={t('pg.next')}><Icon name="chev" size={14} /></button>
	</nav>
{/if}
