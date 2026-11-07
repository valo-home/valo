<script>
	import { useApp } from '#lib/app.svelte.js';

	let { fields = [], values = $bindable({}), secrets = [], disabled = false } = $props();
	const app = useApp();
	const { t } = app;
	const tx = (x) => (x && typeof x === 'object' ? (x[app.lang] ?? x.en ?? Object.values(x)[0]) : (x ?? ''));
</script>

{#each fields as fd (fd.key)}
	<label class="f">
		<span>{tx(fd.name) || fd.key}{#if fd.required}{' *'}{/if}</span>
		{#if fd.type === 'select'}
			<select class="in" bind:value={values[fd.key]} {disabled}>{#each fd.options || [] as o}<option value={o}>{t.has(`opt.${o}`) ? t(`opt.${o}`) : o}</option>{/each}</select>
		{:else if fd.type === 'number'}
			<input class="in" type="number" step="any" bind:value={values[fd.key]} {disabled} />
		{:else if fd.type === 'bool'}
			<input type="checkbox" bind:checked={values[fd.key]} {disabled} />
		{:else}
			<input
				class="in"
				type={fd.type === 'secret' ? 'password' : 'text'}
				autocomplete={fd.type === 'secret' ? 'new-password' : 'off'}
				placeholder={fd.type === 'secret' ? (secrets.includes(fd.key) ? t('ext.secret_set') : '') : String(fd.default ?? '')}
				bind:value={values[fd.key]}
				{disabled}
			/>
		{/if}
		{#if fd.hint}<small class="dim">{tx(fd.hint)}</small>{/if}
	</label>
{/each}
