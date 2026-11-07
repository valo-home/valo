import { fail, redirect } from '@sveltejs/kit';
import { backend } from '#lib/server/backend.js';
import { errorText, setToken } from '#lib/server/session.js';

export async function load({ locals }) {
	const st = await backend(locals, 'GET', '/setup');
	if (st.ok && st.data.done) redirect(303, `/${locals.lang}/login`);
	return { status: st.data };
}

const num = (x) => Number(String(x ?? '').replace(',', '.'));

export const actions = {
	default: async ({ request, locals, cookies, url }) => {
		const f = Object.fromEntries(await request.formData());
		const lang = locals.lang;
		if (String(f.password || '') !== String(f.password2 || '')) return fail(400, { error: 'password_mismatch' });
		const setup = {
			owner: { username: String(f.username || '').trim(), name: String(f.name || '').trim(), password: String(f.password || ''), lang },
			home: { name: String(f.home || '').trim(), lat: num(f.lat), lon: num(f.lon), timezone: String(f.timezone || ''), currency: String(f.currency || ''), settings: { lang } }
		};
		const r = await backend(locals, 'POST', '/setup', setup);
		if (!r.ok) {
			console.error('setup failed', r.status, r.data?.code);
			return fail(r.status, { error: errorText(r) });
		}
		setToken(cookies, url, r.data.token);
		redirect(303, `/${lang}`);
	}
};
