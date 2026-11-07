<script>
	import { onMount } from 'svelte';
	import { useApp } from '#lib/app.svelte.js';

	let { compact = false } = $props();
	const app = useApp();
	const { f, t } = app;
	let now = $state(new Date());
	onMount(() => {
		const i = setInterval(() => (now = new Date()), 1000);
		return () => clearInterval(i);
	});
</script>

<div class="bclock" class:cmp={compact}>
	<b class="num">{f.time(now)}</b>
	<span class="day">{f.day(now)}</span>
	<span class="dim sm">{t('w.week', { n: f.week(now) })}</span>
</div>

<style>
	.bclock {
		display: grid;
		gap: 2px;
	}
	.bclock b {
		font: 300 44px/1.05 var(--f-d);
		letter-spacing: -0.02em;
	}
	.bclock.cmp b {
		font-size: 36px;
	}
	.day {
		font-size: 15px;
		color: var(--ink);
	}
	.day::first-letter {
		text-transform: uppercase;
	}
</style>
