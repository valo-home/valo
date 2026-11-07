<script>
	import { ICONS } from '#lib/icons.js';
	let { name, size = 18 } = $props();
</script>

<svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{@html ICONS[name] || ICONS.dev}</svg>
