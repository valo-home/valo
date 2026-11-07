<script>
	import { useApp } from '#lib/app.svelte.js';

	let { p } = $props();
	const { t } = useApp();
</script>

{#if p.st.failed}
	<div class="row" style="justify-content:center;margin-top:10px"><span class="sm" style="color:var(--crit)">{t('pg.failed')}</span><button class="btn s" onclick={() => p.next()}>{t('pg.retry')}</button></div>
{:else if p.st.more}
	<div style="text-align:center;margin-top:10px"><button class="btn" disabled={p.st.busy} onclick={() => p.next()}>{p.st.busy ? t('w.loading') : t('pg.more')}</button></div>
{:else if p.st.items.length > 20}
	<div class="sm dim" style="text-align:center;margin-top:10px">{t('pg.end', { n: p.st.items.length })}</div>
{/if}
