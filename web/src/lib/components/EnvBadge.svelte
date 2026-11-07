<script>
	let { env, t, peers = true } = $props();
	const label = (n) => (t.has(`env.${n}`) ? t(`env.${n}`) : n);
	const href = (url) => {
		if (typeof location === 'undefined') return url;
		return url.replace(/\/+$/, '') + location.pathname + location.search;
	};
</script>

{#if env?.name}
	<span class="envw">
		<span class="envb {env.demo ? 'demo' : 'real'}" title={t(env.demo ? 'env.hint_demo' : 'env.hint_real')}>{label(env.name)}</span>
		{#if peers}
			{#each env.peers || [] as p}
				<a class="envp" href={href(p.url)} title={t('env.open', { name: label(p.name) })}>{label(p.name)}</a>
			{/each}
		{/if}
	</span>
{/if}
