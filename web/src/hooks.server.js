import { LANGS, pick } from '#lib/i18n/index.js';
import { BACKEND } from '#lib/server/backend.js';

function clientIp(event) {
	try {
		return event.getClientAddress();
	} catch {
		return '';
	}
}

const SKIP = new Set(['connection', 'keep-alive', 'transfer-encoding', 'content-encoding', 'content-length', 'host', 'cookie']);

async function proxy(event) {
	const req = event.request;
	const headers = new Headers();
	for (const [k, v] of req.headers) if (!SKIP.has(k)) headers.set(k, v);
	const token = event.cookies.get('valo_token');
	if (token && !headers.has('authorization')) headers.set('authorization', `Bearer ${token}`);
	headers.set('accept-language', event.cookies.get('lang') || LANGS[0]);
	const ip = clientIp(event);
	if (ip) headers.set('x-forwarded-for', ip);
	try {
		const body = ['GET', 'HEAD'].includes(req.method) ? undefined : await req.arrayBuffer();
		const res = await fetch(BACKEND() + event.url.pathname + event.url.search, { method: req.method, headers, body, redirect: 'manual' });
		const out = new Headers();
		for (const [k, v] of res.headers) if (!SKIP.has(k)) out.set(k, v);
		return new Response(res.body, { status: res.status, headers: out });
	} catch (e) {
		console.error('api proxy failed', req.method, event.url.pathname, e.message);
		return new Response(JSON.stringify({ status: 502, code: 'backend_unavailable', title: 'backend unavailable' }), {
			status: 502,
			headers: { 'content-type': 'application/problem+json' }
		});
	}
}

export async function handle({ event, resolve }) {
	const { pathname, search } = event.url;
	if (pathname.startsWith('/api/')) return proxy(event);
	const lang = pathname.split('/')[1];
	if (!LANGS.includes(lang)) {
		const want = pick(event.cookies.get('lang'), event.request.headers.get('accept-language'));
		return new Response(null, { status: 307, headers: { location: `/${want}${pathname === '/' ? '' : pathname}${search}` } });
	}
	if (event.cookies.get('lang') !== lang) event.cookies.set('lang', lang, { path: '/', maxAge: 31536000, httpOnly: false, sameSite: 'lax' });
	event.locals.lang = lang;
	event.locals.token = event.cookies.get('valo_token') || '';
	event.locals.ip = clientIp(event);
	return resolve(event, { transformPageChunk: ({ html }) => html.replace('%lang%', lang) });
}

export async function handleError({ error, event, status, message }) {
	console.error('web error', status, event.url.pathname, error?.stack || error);
	const token = event.cookies.get('valo_token');
	if (status !== 404 && token) {
		fetch(BACKEND() + '/api/v1/system/errors/report', {
			method: 'POST',
			headers: { 'content-type': 'application/json', authorization: `Bearer ${token}` },
			body: JSON.stringify({ source: 'web', message: String(error?.message || message).slice(0, 300), stack: String(error?.stack || '').slice(0, 6000), url: event.url.pathname })
		}).catch((e) => console.error('error report failed', e.message));
	}
	return { message };
}
