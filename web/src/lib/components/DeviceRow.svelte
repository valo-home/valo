<script>
	import { useApp } from '#lib/app.svelte.js';
	import { icon, isOn, lowBat, primary } from '#lib/devices.js';
	import Control from './Control.svelte';
	import Icon from './Icon.svelte';

	let { d, onnav } = $props();
	const app = useApp();
</script>

<div class="drow">
	<div class="dico" class:on={isOn(d)}><Icon name={icon(d)} size={17} /></div>
	<div style="min-width:0">
		<a class="dn" href={app.path(`/devices/${encodeURIComponent(d.id)}`)} onclick={onnav}>{d.name}</a>
		<div class="ds">
			{primary(app, d)}{#if typeof d.state.bat === 'number'}{' · '}<span class="bat" class:low={lowBat(d)}>{d.state.bat}%</span>{/if}
		</div>
	</div>
	<Control {d} />
</div>
