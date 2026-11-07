import { DICTS } from '#lib/server/dicts.js';

export function load({ locals }) {
	return { lang: locals.lang, dict: DICTS[locals.lang] };
}
