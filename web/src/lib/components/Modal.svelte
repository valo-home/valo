<script>
	import { getContext } from 'svelte';
	import Icon from './Icon.svelte';

	let { title = '', sub = '', kind = 'modal', wide = false, icon = '', children, foot, onclose } = $props();
	const t = getContext('t');
	let open = $state(false);
	let dlg = $state();

	export const show = () => (open = true);
	export const hide = () => dlg?.close();
</script>

{#if open}
	<dialog
		bind:this={dlg}
		class={kind}
		class:wide
		{@attach (el) => el.showModal()}
		onclose={() => ((open = false), onclose?.())}
		onclick={(e) => e.target === e.currentTarget && hide()}
	>
		<div class={kind === 'drawer' ? 'drh' : 'mh'}>
			{#if icon}<div class="dico on"><Icon name={icon} /></div>{/if}
			<div style="flex:1;min-width:0">
				<h2>{title}</h2>
				{#if sub}<div class="ds">{sub}</div>{/if}
			</div>
			<button class="ib" onclick={hide} aria-label={t('a.close')}><Icon name="x" /></button>
		</div>
		<div class={kind === 'drawer' ? 'drb' : 'mbd'}>
			{@render children()}
			{#if foot}<div class="mf">{@render foot()}</div>{/if}
		</div>
	</dialog>
{/if}
