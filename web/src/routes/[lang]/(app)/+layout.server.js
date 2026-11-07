import { error, redirect } from '@sveltejs/kit';
import { backend } from '#lib/server/backend.js';
import { clearToken } from '#lib/server/session.js';

export async function load({ locals, cookies, url }) {
	const L = locals.lang;
	if (!locals.token) {
		const st = await backend(locals, 'GET', '/setup');
		redirect(303, st.ok && !st.data.done ? `/${L}/setup` : `/${L}/login?next=${encodeURIComponent(url.pathname + url.search)}`);
	}
	const [me, overview] = await Promise.all([backend(locals, 'GET', '/auth/me'), backend(locals, 'GET', '/overview')]);
	if (me.status === 401 || overview.status === 401) {
		clearToken(cookies);
		redirect(303, `/${L}/login`);
	}
	if (!me.ok || !overview.ok) {
		console.error('app load failed', me.status, overview.status);
		error(502, overview.data?.title || 'backend unavailable');
	}
	return { me: me.data, overview: overview.data };
}
