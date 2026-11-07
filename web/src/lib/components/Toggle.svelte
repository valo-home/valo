<script>
	let { on = false, pending = false, label = '', disabled = false, onclick } = $props();
</script>

<button class="tg" class:on class:pend={pending} aria-pressed={on} aria-label={label} {disabled} {onclick}></button>
