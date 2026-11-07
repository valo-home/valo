<script>
	import { getContext } from 'svelte';
	import { page } from '$app/state';

	const t = getContext('t');
</script>

<svelte:head><title>{page.status} · valo</title></svelte:head>

<div class="wiz">
	<div class="brand" style="padding:0"><div class="logo"></div><div><b>valo</b><small>{page.status}</small></div></div>
	<section class="card g" style="gap:12px;margin-top:24px">
		<h2 style="margin:0">{t ? t(page.status === 404 ? 'err.404' : 'err.other') : page.status}</h2>
		<p class="dim" style="margin:0">{page.error?.message}</p>
		<div><a class="btn" href="/{page.params.lang || ''}">{t ? t('err.home') : 'valo'}</a></div>
	</section>
</div>
