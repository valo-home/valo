<script>
	let { q } = $props();
</script>

<span class="lqi" class:weak={q < 60}>{#each [1, 2, 3, 4] as k}<i class:f={q >= k * 50} style="height:{k * 3}px"></i>{/each}</span> <span class="mono sm">{q}</span>
