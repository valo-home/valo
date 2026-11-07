import { BACKEND_URL } from '$app/env/private';

export const BACKEND = () => BACKEND_URL;

export async function backend(locals, method, path, body) {
	const headers = { 'accept-language': locals.lang, 'x-forwarded-for': locals.ip || '' };
	if (locals.token) headers.authorization = `Bearer ${locals.token}`;
	if (body !== undefined) headers['content-type'] = 'application/json';
	try {
		const r = await fetch(`${BACKEND()}/api/v1${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
		const data = r.status === 204 ? null : await r.json().catch(() => null);
		if (!r.ok && r.status >= 500) console.error('backend call failed', method, path, r.status);
		return { ok: r.ok, status: r.status, data };
	} catch (e) {
		console.error('backend unreachable', method, path, e.message);
		return { ok: false, status: 502, data: { code: 'backend_unavailable', detail: e.message } };
	}
}
