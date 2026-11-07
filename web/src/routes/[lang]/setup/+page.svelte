<script>
	import { getContext } from 'svelte';
	import Icon from '#lib/components/Icon.svelte';

	import { enhance } from '$app/forms';

	let { data, form } = $props();
	const t = getContext('t');
	const STEPS = ['setup.s_home', 'setup.s_links', 'setup.s_owner', 'setup.s_done'];
	const init = (() => ({ step: 0, st: data.status, v: { home: '', lat: '60.17', lon: '24.94', timezone: 'Europe/Helsinki', currency: 'EUR', name: '', username: '', password: '', password2: '' } }))();
	let step = $state(init.step);
	let st = $state(init.st);
	let v = $state(init.v);
	const local = (() => {
		try {
			const z = Intl.DateTimeFormat().resolvedOptions().timeZone || '';
			return z === 'Europe/Kiev' ? 'Europe/Kyiv' : z;
		} catch (e) {
			console.warn('time zone unknown', e?.message);
			return '';
		}
	})();
	const zones = [...new Set([...(local ? [local] : []), 'Europe/Helsinki', 'Europe/Stockholm', 'Europe/Oslo', 'Europe/Copenhagen', 'Europe/Tallinn', 'Europe/Riga', 'Europe/Vilnius', 'Europe/Berlin', 'Europe/Kyiv', 'Europe/Warsaw'])];
	if (local) v.timezone = local;
	let ad = $state(null);
	let pick = $state({ path: '', type: '' });
	let linking = $state(false);
	let adErr = $state('');
	async function adapters() {
		try {
			const r = await fetch('/api/v1/setup/adapters');
			if (!r.ok) throw new Error(`${r.status}`);
			ad = await r.json();
			const first = ad.adapters.find((a) => a.path === ad.current?.path) || ad.adapters[0];
			if (first && !pick.path) pick = { path: first.path, type: ad.current?.type || first.type || 'ember' };
		} catch (e) {
			console.warn('adapters load failed', e?.message);
			adErr = e.message;
		}
	}
	async function link() {
		linking = true;
		adErr = '';
		try {
			const r = await fetch('/api/v1/setup/adapter', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(pick) });
			const body = await r.json().catch(() => ({}));
			if (!r.ok) throw new Error(body.title || body.detail || `${r.status}`);
			ad = body;
			for (let i = 0; i < 30 && st?.zigbee !== 'online'; i++) {
				await new Promise((res) => setTimeout(res, 3000));
				await refresh();
			}
			if (st?.zigbee !== 'online') adErr = t('setup.adapter_wait');
		} catch (e) {
			console.warn('adapter choose failed', e?.message);
			adErr = e.message;
		} finally {
			linking = false;
		}
	}
	$effect(() => {
		if (step === 1 && !ad) adapters();
	});
	const ok = $derived([v.home.trim() && v.lat && v.lon, true, v.name.trim() && v.username.trim() && v.password.length >= 6 && v.password === v.password2, true][step]);
	let busy = $state(false);
	const finish = () => {
		busy = true;
		return async ({ update }) => {
			await update({ reset: false });
			busy = false;
		};
	};
	const refresh = async () => (st = await fetch('/api/v1/setup').then((r) => (r.ok ? r.json() : st)).catch(() => st));
</script>

<svelte:head><title>{t('setup.title')} · valo</title></svelte:head>

<form class="wiz" method="POST" use:enhance={finish}>
	<div class="brand" style="padding:0"><div class="logo"></div><div><b>valo</b><small>{t('setup.sub')}</small></div></div>
	<div class="wst">
		{#each STEPS as k, i}<span class:on={i === step} class:done={i < step}>{#if i < step}<Icon name="check" size={13} />{:else}{i + 1}{/if} {t(k)}</span>{/each}
	</div>
	<section class="card g" style="gap:16px">
		<div class="g" style="gap:16px" hidden={step !== 0}>
			<h2 style="margin:0">{t('setup.home_title')}</h2>
			<p class="dim" style="margin:0">{t('setup.home_hint')}</p>
			<div class="fg">
				<label class="f">{t('setup.home_name')}<input class="in" name="home" bind:value={v.home} required /></label>
				<label class="f">{t('setup.lat')}<input class="in" name="lat" bind:value={v.lat} inputmode="decimal" /></label>
				<label class="f">{t('setup.lon')}<input class="in" name="lon" bind:value={v.lon} inputmode="decimal" /></label>
				<label class="f">{t('setup.tz')}<select class="in" name="timezone" bind:value={v.timezone}>{#each zones as z}<option>{z}</option>{/each}</select></label>
				<label class="f">{t('setup.currency')}<select class="in" name="currency" bind:value={v.currency}>{#each ['EUR', 'SEK', 'NOK', 'DKK'] as c}<option>{c}</option>{/each}</select></label>
			</div>
		</div>
		<div class="g" style="gap:16px" hidden={step !== 1}>
			<h2 style="margin:0">{t('setup.links_title')}</h2>
			<div class="lst">
				<div class="opt" class:on={st?.broker}><span class="dico" class:on={st?.broker}><Icon name="mqtt" size={16} /></span><span><b style="font-weight:500">{t('setup.broker')}</b><br /><span class="sm dim">{st?.broker ? t('setup.broker_ok') : t('setup.broker_no')}</span></span>{#if st?.broker}<Icon name="check" size={16} />{/if}</div>
				<div class="opt" class:on={st?.zigbee === 'online'}><span class="dico" class:on={st?.zigbee === 'online'}><Icon name="zig" size={16} /></span><span><b style="font-weight:500">{t('setup.zigbee')}</b><br /><span class="sm dim">{st?.zigbee === 'online' ? t('setup.zigbee_ok', { type: st.coordinator || '-', ch: st.channel ?? '-' }) : t('setup.zigbee_no')}</span></span>{#if st?.zigbee === 'online'}<Icon name="check" size={16} />{/if}</div>
			</div>
			{#if st?.zigbee !== 'online' && ad}
				<div class="g" style="gap:10px">
					<b style="font-weight:500">{t('setup.adapter_title')}</b>
					{#if ad.current?.source === 'env'}
						<p class="sm dim" style="margin:0">{t('setup.adapter_env', { path: ad.current.path })}</p>
					{:else if ad.adapters.length}
						{#each ad.adapters as a (a.path)}
							<label class="row sm"><input type="radio" name="adapter" checked={pick.path === a.path} onchange={() => (pick = { path: a.path, type: a.type || pick.type || 'ember' })} />{a.name}</label>
						{/each}
						<label class="f">{t('setup.adapter_type')}<select class="in" bind:value={pick.type}>{#each ad.types as k}<option value={k}>{t(`setup.at_${k}`)}</option>{/each}</select></label>
						<div><button class="btn pri s" type="button" onclick={link} disabled={linking || !pick.path}><Icon name="zig" size={14} />{linking ? t('setup.adapter_linking') : t('setup.adapter_use')}</button></div>
					{:else}
						<p class="sm dim" style="margin:0">{t('setup.adapter_none')}</p>
					{/if}
					{#if adErr}<p class="err sm" style="margin:0">{adErr}</p>{/if}
				</div>
			{/if}
			<p class="sm dim" style="margin:0">{t('setup.links_hint')}</p>
			<div><button class="btn s" type="button" onclick={() => (refresh(), adapters())}><Icon name="refresh" size={14} />{t('a.refresh')}</button></div>
		</div>
		<div class="g" style="gap:16px" hidden={step !== 2}>
			<h2 style="margin:0">{t('setup.owner_title')}</h2>
			<div class="fg">
				<label class="f">{t('setup.owner_name')}<input class="in" name="name" bind:value={v.name} autocomplete="name" /></label>
				<label class="f">{t('login.user')}<input class="in" name="username" bind:value={v.username} autocomplete="username" /></label>
				<label class="f">{t('login.password')}<input class="in" name="password" type="password" bind:value={v.password} autocomplete="new-password" /></label>
				<label class="f">{t('setup.password2')}<input class="in" name="password2" type="password" bind:value={v.password2} autocomplete="new-password" /></label>
			</div>
			<p class="sm dim" style="margin:0">{t('setup.password_hint')}</p>
		</div>
		<div class="g" style="gap:16px" hidden={step !== 3}>
			<h2 style="margin:0">{t('setup.done_title')}</h2>
			<dl class="kv">
				<dt>{t('setup.s_home')}</dt><dd>{v.home}, {v.timezone}</dd>
				<dt>{t('setup.currency')}</dt><dd>{v.currency}</dd>
				<dt>Zigbee</dt><dd>{st?.zigbee === 'online' ? `${st.coordinator || ''} ${st.channel ?? ''}` : t('setup.zigbee_no')}</dd>
				<dt>{t('setup.s_owner')}</dt><dd>{v.name} ({v.username})</dd>
			</dl>
		</div>
		{#if v.password2 && v.password !== v.password2}<p class="err" style="margin:0">{t('setup.mismatch')}</p>{/if}
		{#if form?.error}<p class="err" style="margin:0" role="alert">{form.error === 'password_mismatch' ? t('setup.mismatch') : form.error}</p>{/if}
		<div class="mf">
			{#if step > 0}<button class="btn" type="button" onclick={() => step--}>{t('a.back')}</button>{/if}
			{#if step < 3}<button class="btn pri" type="button" disabled={!ok} onclick={() => step++}>{t('a.next')}</button>{:else}<button class="btn pri" type="submit" disabled={busy}>{t('setup.finish')}</button>{/if}
		</div>
	</section>
</form>
