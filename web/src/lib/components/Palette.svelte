<script>
	import { goto } from '$app/navigation';
	import { useApp } from '#lib/app.svelte.js';
	import { canWrite, icon } from '#lib/devices.js';
	import Icon from './Icon.svelte';

	let { pages = [] } = $props();
	const app = useApp();
	const { s, t } = app;
	let open = $state(false);
	let q = $state('');
	let sel = $state(0);
	let dlg = $state();

	export const show = () => ((q = ''), (sel = 0), (open = true));

	const items = $derived.by(() => {
		const k = q.trim().toLowerCase();
		const m = (x) => !k || x.toLowerCase().includes(k);
		const room = (id) => s.rooms.find((r) => r.id === id)?.name ?? '';
		const out = [];
		for (const p of pages) if (m(p.label)) out.push({ g: 'ck.pages', icon: p.icon, label: p.label, go: p.href });
		for (const d of Object.values(s.devices)) {
			if (!m(d.name)) continue;
			out.push({ g: 'ck.devices', icon: icon(d), label: d.name, hint: room(d.roomId), go: app.path(`/devices/${encodeURIComponent(d.id)}`) });
			if (k && d.available && canWrite(d, 'on')) out.push({ g: 'ck.actions', icon: 'power', label: t(d.state.on ? 'ck.off' : 'ck.on', { name: d.name }), act: () => app.cmd(d.id, { on: !d.state.on }) });
		}
		for (const x of s.scenes) if (m(x.name)) out.push({ g: 'ck.scenes', icon: x.icon, label: x.name, act: () => app.run(() => app.api('POST', `/scenes/${x.id}/apply`), t('scenes.applied', { name: x.name })) });
		for (const x of s.flows) if (m(x.name)) out.push({ g: 'ck.flows', icon: 'flow', label: x.name, go: app.path(`/flows/${x.id}`) });
		for (const x of s.rooms) if (m(x.name)) out.push({ g: 'ck.rooms', icon: 'rooms', label: x.name, go: app.path(`/rooms?room=${x.id}`) });
		return out.slice(0, 50);
	});

	function exec(it) {
		if (!it) return;
		dlg?.close();
		it.go ? goto(it.go) : it.act();
	}

	function key(e) {
		if (e.key === 'ArrowDown') (e.preventDefault(), (sel = Math.min(items.length - 1, sel + 1)));
		else if (e.key === 'ArrowUp') (e.preventDefault(), (sel = Math.max(0, sel - 1)));
		else if (e.key === 'Enter') exec(items[sel]);
	}
</script>

{#if open}
	<dialog class="ck" bind:this={dlg} {@attach (el) => el.showModal()} onclose={() => (open = false)} onclick={(e) => e.target === e.currentTarget && dlg.close()}>
		<input placeholder={t('ck.placeholder')} aria-label={t('ck.placeholder')} bind:value={q} onkeydown={key} oninput={() => (sel = 0)} />
		<div class="res">
			{#each items as it, i}
				{#if i === 0 || items[i - 1].g !== it.g}<h6>{t(it.g)}</h6>{/if}
				<button class="ri" class:on={i === sel} onclick={() => exec(it)} onmousemove={() => (sel = i)}><Icon name={it.icon} size={16} />{it.label}{#if it.hint}<small>{it.hint}</small>{/if}</button>
			{:else}
				<p class="dim sm" style="padding:10px">{t('ck.none')}</p>
			{/each}
		</div>
	</dialog>
{/if}
