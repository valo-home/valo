import { untrack } from 'svelte';
import { replaceState } from '$app/navigation';
import { page } from '$app/state';

export function keepTab(value, fallback) {
	untrack(() => {
		const u = new URL(location.href);
		if (value === fallback) u.searchParams.delete('tab');
		else u.searchParams.set('tab', value);
		if (u.href !== location.href) replaceState(u, page.state);
	});
}
