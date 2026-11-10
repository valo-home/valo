import { capName, value } from '#lib/devices.js';
import { values } from '#lib/flowtext.js';

const LEVEL_ICON = { crit: 'warn', warn: 'warn', ok: 'check', info: 'log' };
export const levelIcon = (l) => LEVEL_ICON[l] || 'log';

function human(app, v) {
	if (v == null) return '';
	if (typeof v === 'boolean') return app.t(v ? 'v.yes' : 'v.no');
	if (typeof v === 'number') return app.f.n(v, Number.isInteger(v) ? 0 : 1);
	if (Array.isArray(v)) return v.map((x) => human(app, x)).join(', ');
	if (typeof v === 'object') return Object.entries(v).map(([k, x]) => `${app.t.has(`cap.${k}`) ? app.t(`cap.${k}`) : k} ${human(app, x)}`).join(', ');
	return String(v);
}

const CAM_FIELDS = {
	name: 'devs.name',
	room: 'devs.room',
	sort: 'cam.sort',
	config: 'cam.t_connection',
	'record.mode': 'cam.recording',
	'record.snapshots': 'cam.rec_snapshots',
	'record.pre': 'cam.pre',
	'record.post': 'cam.post',
	'record.max': 'cam.max',
	'record.labels': 'cam.rec_labels',
	'record.stream': 'cam.rec_stream',
	'record.audio': 'cam.rec_audio',
	'record.schedule': 'cam.schedule',
	'record.keep_days': 'cam.keep_days',
	'record.offline_min': 'cam.offline_min',
	'record.detect': 'cam.t_vision',
	'record.zones': 'cam.vis_zones'
};

function camChange(app, k, v) {
	const { t } = app;
	const name = CAM_FIELDS[k] ? t(CAM_FIELDS[k]) : k;
	if (v == null) return name;
	if (typeof v === 'boolean') return `${name} ${t(v ? 'v.on' : 'v.off')}`;
	if (k === 'record.mode' && t.has(`cam.mode_${v}`)) return `${name} ${t(`cam.mode_${v}`).toLowerCase()}`;
	if (k === 'record.stream') return `${name} ${v === 'sub' ? 'SD' : 'HD'}`;
	return `${name} ${human(app, v)}`;
}

export function evText(app, e) {
	const { t, s } = app;
	const p = Object.fromEntries(Object.entries(e.params || {}).map(([k, v]) => [k, human(app, v)]));
	if ((e.type === 'device.state' || e.type.startsWith('command.')) && e.deviceId) {
		const d = s.devices[e.deviceId];
		if (d && e.type === 'device.state') {
			const c = d.caps.find((c) => c.id === e.params.cap);
			p.cap = c ? capName(t, c) : e.params.cap;
			p.value = value(app, { ...d, state: { [e.params.cap]: e.params.value } }, e.params.cap);
			if (typeof e.params.value !== 'boolean' || String(e.params.cap).includes('_')) p.value = `${p.cap} ${p.value}`;
		}
		if (d && e.type.startsWith('command.') && e.params.values && typeof e.params.values === 'object') p.values = values(app, e.deviceId, e.params.values);
	}
	if (e.type === 'device.moved') for (const k of ['room', 'old']) p[k] = s.rooms.find((r) => r.id === e.params[k])?.name ?? t('devs.no_room');
	if (e.type === 'camera.updated' && e.params?.changes && typeof e.params.changes === 'object') {
		p.what = Object.entries(e.params.changes).map(([k, v]) => camChange(app, k, v)).join(', ');
		if (p.what) return t('e.camera.updated_what', p);
	}
	const key = `e.${e.type}`;
	return t.has(key) ? t(key, p) : [e.type, p.name].filter(Boolean).join(' ');
}

export function actor(app, a) {
	const { t, s } = app;
	if (!a || a === 'system') return t('actor.system');
	const i = a.indexOf(':');
	const k = a.slice(0, i);
	const v = a.slice(i + 1);
	if (k === 'user') return t('actor.user', { name: v === s.me?.username && s.me.name ? s.me.name : v });
	if (k === 'flow') return t('actor.flow', { name: s.flows.find((f) => f.id === v)?.name ?? v });
	if (k === 'ext') {
		const n = [...(s.contrib?.pages || []), ...(s.contrib?.widgets || [])].find((x) => x.ext === v)?.extName;
		return t('actor.ext', { name: (n && typeof n === 'object' ? n[app.lang] || n.en : n) || v });
	}
	if (k === 'token') return t('actor.token', { name: v });
	return a;
}

export function notifText(app, n) {
	const p = Object.fromEntries(Object.entries(n.params || {}).map(([k, v]) => [k, human(app, v)]));
	return app.t.has(`n.${n.type}`) ? app.t(`n.${n.type}`, p) : n.type;
}

export function route(app, r) {
	if (!r) return app.path('/');
	const [k, ...rest] = r.split('/');
	if (k === 'ext' && rest.length) return app.path(`/extensions?open=${encodeURIComponent(rest.join('/'))}`);
	const map = { devices: '/devices/', flows: '/flows/', ext: '/extensions', zigbee: '/zigbee', system: '/system' };
	return app.path((map[k] ?? `/${k}`) + rest.map(encodeURIComponent).join('/'));
}

export function routeName(app, r) {
	const { t, s } = app;
	const [k, ...rest] = (r || '').split('/');
	const id = rest.join('/');
	if (k === 'devices' && id) return s.devices[id]?.name ?? id;
	if (k === 'flows' && id) return s.flows.find((x) => x.id === id)?.name ?? id;
	if (k === 'ext' && id) {
		const n = s.contrib?.exts?.find((x) => x.id === id)?.name;
		return `${t('nav.extensions')} · ${(n && typeof n === 'object' ? (n[app.lang] ?? n.en ?? Object.values(n)[0]) : n) || id}`;
	}
	return k && t.has(`nav.${k}`) ? t(`nav.${k}`) : t('nav.home');
}
