const COOKIE = { path: '/', httpOnly: true, sameSite: 'lax', maxAge: 30 * 86400 };

export function setToken(cookies, url, token) {
	cookies.set('valo_token', token, { ...COOKIE, secure: url.protocol === 'https:' });
}

export function clearToken(cookies) {
	cookies.delete('valo_token', { path: '/' });
}

export function errorText(r) {
	return r.data?.title || r.data?.detail || String(r.status);
}

export function safeNext(next, lang) {
	return next && next.startsWith(`/${lang}`) && !next.startsWith('//') ? next : `/${lang}`;
}
