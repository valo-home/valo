<script>
	import { getContext } from 'svelte';
	import EnvBadge from '#lib/components/EnvBadge.svelte';

	import { enhance } from '$app/forms';

	let { data, form } = $props();
	const t = getContext('t');
	let busy = $state(false);
	const submit = () => {
		busy = true;
		return async ({ update }) => {
			await update({ reset: false });
			busy = false;
		};
	};
</script>

<svelte:head><title>{t('login.title')} · valo</title></svelte:head>

<div class="auth">
	<div class="art">
		<svg viewBox="0 0 640 400" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
			<defs><radialGradient id="ga"><stop offset="0" stop-color="#ffa64a" stop-opacity=".5" /><stop offset="1" stop-color="#ffa64a" stop-opacity="0" /></radialGradient></defs>
			{#each [[20, 20, 310, 210], [330, 20, 190, 210], [520, 20, 100, 210], [20, 230, 150, 150], [170, 230, 120, 150], [290, 230, 120, 150], [410, 230, 110, 150]] as [x, y, w, h]}
				<rect {x} {y} width={w} height={h} rx="6" style="fill:none;stroke:var(--line-2)" />
			{/each}
			<circle cx="175" cy="125" r="130" fill="url(#ga)" /><circle cx="465" cy="305" r="70" fill="url(#ga)" />
		</svg>
		<p>{t('login.art')}</p>
	</div>
	<div class="form">
		<form class="card" method="POST" use:enhance={submit} style="width:min(380px,100%);display:grid;gap:14px;padding:24px">
			<div class="brand" style="padding:0"><div class="logo"></div><div><b>valo</b><small>{t('login.sub')}</small></div><span style="margin-left:auto"><EnvBadge env={data.env} {t} /></span></div>
			<label class="f">{t('login.user')}<input class="in" name="username" autocomplete="username" value={form?.username ?? ''} required /></label>
			<label class="f">{t('login.password')}<input class="in" name="password" type="password" autocomplete="current-password" required /></label>
			{#if form?.error}<p class="err" style="margin:0" role="alert">{form.error}</p>{/if}
			<button class="btn pri" type="submit" disabled={busy}>{t('a.login')}</button>
			<p class="sm dim" style="margin:0">{t('login.note')}</p>
		</form>
	</div>
</div>
