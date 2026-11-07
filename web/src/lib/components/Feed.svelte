<script>
	import { useApp } from '#lib/app.svelte.js';
	import { actor, evText } from '#lib/events.js';

	let { events, limit = 8, onpick } = $props();
	const app = useApp();
</script>

{#each events.slice(0, limit) as e (e.id)}
	<div class="ev {e.level}">
		<time>{app.f.time(e.ts)}</time>
		<div>
			{#if onpick}<button class="dn" onclick={() => onpick(e)}><b>{evText(app, e)}</b></button>{:else}<b>{evText(app, e)}</b>{/if}
			<span class="why">{actor(app, e.actor)}</span>
		</div>
	</div>
{:else}
	<p class="dim sm">{app.t('log.empty')}</p>
{/each}
