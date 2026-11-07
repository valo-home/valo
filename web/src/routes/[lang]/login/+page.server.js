import { fail, redirect } from '@sveltejs/kit';
import { backend } from '#lib/server/backend.js';
import { errorText, safeNext, setToken } from '#lib/server/session.js';

export async function load({ locals }) {
	if (locals.token) redirect(303, `/${locals.lang}`);
	const st = await backend(locals, 'GET', '/setup');
	if (st.ok && !st.data.done) redirect(303, `/${locals.lang}/setup`);
	return { env: st.ok ? st.data.env : null };
}

export const actions = {
	default: async ({ request, locals, cookies, url }) => {
		const f = await request.formData();
		const username = String(f.get('username') || '').trim();
		const r = await backend(locals, 'POST', '/auth/login', { username, password: String(f.get('password') || '') });
		if (!r.ok) {
			console.error('login failed', r.status, r.data?.code);
			return fail(r.status, { error: errorText(r), username });
		}
		setToken(cookies, url, r.data.token);
		redirect(303, safeNext(url.searchParams.get('next'), locals.lang));
	}
};
