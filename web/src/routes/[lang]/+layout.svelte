<script>
	import '../../app.css';
	import { setContext } from 'svelte';
	import { translator } from '#lib/i18n/index.js';

	let { data, children } = $props();
	setContext('t', translator(() => data.dict, () => data.lang));
</script>

{@render children()}
