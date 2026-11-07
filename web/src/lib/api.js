export class ApiError extends Error {
	constructor(message, status, data) {
		super(message);
		this.status = status;
		this.data = data;
	}
}

export async function api(method, path, body) {
	const init = { method, headers: {} };
	if (body !== undefined || method !== 'GET') {
		init.headers['content-type'] = 'application/json';
		init.body = JSON.stringify(body ?? {});
	}
	const r = await fetch(`/api/v1${path}`, init);
	if (r.status === 401 && typeof location !== 'undefined') {
		location.href = `/${document.documentElement.lang}/login?next=${encodeURIComponent(location.pathname)}`;
	}
	const data = r.status === 204 ? null : await r.json().catch(() => null);
	if (!r.ok) {
		console.error('api error', method, path, r.status, data?.code);
		throw new ApiError(data?.title || data?.detail || r.statusText, r.status, data);
	}
	return data;
}
