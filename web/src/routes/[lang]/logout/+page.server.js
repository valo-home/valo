import { redirect } from '@sveltejs/kit';
import { clearToken } from '#lib/server/session.js';

export function load({ locals }) {
	redirect(303, `/${locals.lang}`);
}

export const actions = {
	default: ({ cookies, locals }) => {
		clearToken(cookies);
		redirect(303, `/${locals.lang}/login`);
	}
};
