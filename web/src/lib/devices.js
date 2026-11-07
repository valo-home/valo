export const KIND_ICON = {
	light: 'bulb', switch: 'power', plug: 'plug', clim: 'thermo', trv: 'trv', button: 'remote', motion: 'motion', contact: 'door',
	leak: 'drop', smoke: 'warn', blind: 'blind', meter: 'bolt', boiler: 'tank', sauna: 'flame', floor: 'heat', price: 'chart', presence: 'user',
	lock: 'lock', fan: 'fan', weather: 'cloud', air: 'wind', calendar: 'calendar', timer: 'clock', clock: 'clock', safety: 'shield', plugguard: 'plug', camera: 'camera'
};
const SUFFIX = /^(.+)_(l\d+|\d+|left|right|center|top|bottom)$/;
export const KINDS = Object.keys(KIND_ICON).concat('other');
const DEC = { t: 1, sp: 1, target: 1, kwh: 1, p: 1, v: 1, a: 2, pa: 0, w: 0, h: 0, bri: 0, pos: 0, bat: 0, lux: 0, co2: 0, pm25: 0, voc: 0, today_kwh: 2, month_kwh: 1, year_kwh: 0, today_cost: 2, month_cost: 2, year_cost: 2, price: 3, feels: 1, rain: 1, wind: 1, gust: 1, clouds: 0, pressure: 0, aqi: 0, pm10: 0, pollen: 0, remaining: 0, minutes: 0 };
const BOOL = { on: ['v.on', 'v.off'], open: ['v.open', 'v.closed'], leak: ['v.leak', 'v.dry'], occ: ['v.motion', 'v.still'], heat: ['v.heating', 'v.idle'], smoke: ['v.smoke', 'v.clear'], lock: ['v.locked', 'v.unlocked'], locked: ['v.locked', 'v.unlocked'], co: ['v.co', 'v.clear'], gas: ['v.gas', 'v.clear'], silence: ['v.silenced', 'v.sound_on'] };
const boolKey = (id) => BOOL[id] || BOOL[id.match(SUFFIX)?.[1]];
const gangs = (d) => Object.keys(d.state).filter((k) => /^on_/.test(k));

export const icon = (d) => KIND_ICON[d.kind] || 'dev';
export const cap = (d, id) => d.caps.find((c) => c.id === id);
export const canWrite = (d, id) => !!cap(d, id)?.access.includes('w');
export const isOn = (d) => d.available && (d.state.on === true || gangs(d).some((k) => d.state[k] === true) || ((d.kind === 'floor' || d.kind === 'sauna') && d.state.heat === true));
export const alarm = (d) => !d.available || d.state.leak === true || d.state.smoke === true || d.state.co === true || d.state.gas === true;
export const lowBat = (d) => typeof d.state.bat === 'number' && d.state.bat < 15;

export function unit(t, u) {
	return u ? (t.has(`u.${u}`) ? t(`u.${u}`) : u) : '';
}

export function capName(t, c) {
	if (t.has(`cap.${c.id}`)) return t(`cap.${c.id}`);
	const m = c.id.match(SUFFIX);
	if (m && t.has(`cap.${m[1]}`)) return `${t(`cap.${m[1]}`)} ${t.has(`side.${m[2]}`) ? t(`side.${m[2]}`) : m[2].replace(/^l/, '')}`;
	return c.name || c.id;
}

export function powerName(t, raw) {
	if (!raw) return '-';
	const k = /^battery/i.test(raw) ? 'battery' : /^mains/i.test(raw) ? 'mains' : /^dc/i.test(raw) ? 'dc' : '';
	return k ? t(`zb.pw_${k}`) : raw;
}

export const boolLabels = (t, id) => (boolKey(id) || ['v.yes', 'v.no']).map((k) => t(k)).reverse();

export function value(app, d, id, withUnit = true) {
	const { t, f } = app;
	const v = d.state[id];
	if (v == null || v === '') return '-';
	if (typeof v === 'boolean') return t((boolKey(id) || ['v.yes', 'v.no'])[v ? 0 : 1]);
	if (typeof v === 'number') {
		const c = cap(d, id);
		const s = f.n(v, DEC[id] ?? (Number.isInteger(v) ? 0 : 1));
		const u = unit(t, c?.unit);
		return withUnit && u ? `${s}\u00a0${u}` : s;
	}
	return typeof v === 'string' && t.has(`ev.${v}`) ? t(`ev.${v}`) : String(v);
}

export function primary(app, d) {
	const { t, f } = app;
	const s = d.state;
	if (!d.available) return t('v.offline');
	const v = (id) => value(app, d, id);
	switch (d.kind) {
		case 'light':
			return s.on ? (s.bri != null ? v('bri') : t('v.on')) : t('v.off');
		case 'switch':
		case 'plug':
		case 'boiler': {
			const g = gangs(d);
			const st = g.length && s.on == null ? t('home.of', { a: g.filter((k) => s[k]).length, b: g.length }) : s.on ? t('v.on') : t('v.off');
			return st + (s.w ? ` · ${v('w')}` : '');
		}
		case 'lock':
			return v('locked');
		case 'fan':
			return s.on === false ? t('v.off') : s.fan_mode ? String(s.fan_mode) : s.on ? t('v.on') : '-';
		case 'clim':
			return [s.t != null && v('t'), s.h != null && v('h')].filter(Boolean).join(' · ') || '-';
		case 'trv':
		case 'floor':
			return s.t != null ? `${v('t')} → ${f.n(s.sp, 1)}` : '-';
		case 'sauna':
			return `${v('t')}${s.on ? ` · ${t('v.heating')}` : ''}`;
		case 'motion':
		case 'camera':
			return s.occ == null && d.kind === 'camera' ? t('v.online') : v('occ');
		case 'contact':
			return v('open');
		case 'leak':
			return v('leak');
		case 'smoke':
			return s.smoke ? t('v.smoke') : s.co ? t('v.co') : s.gas ? t('v.gas') : t('v.clear');
		case 'blind':
			return v('pos');
		case 'meter':
			return s.w == null ? '-' : Math.abs(s.w) >= 1000 ? `${f.n(s.w / 1000, 2)}\u00a0${unit(t, 'kW')}` : `${f.n(s.w, 0)}\u00a0${unit(t, 'W')}`;
		case 'price':
			return v('p');
		case 'weather':
			return [s.t != null && v('t'), s.cond && v('cond')].filter(Boolean).join(' · ') || '-';
		case 'air':
			return s.aqi != null ? `${t('cap.aqi')} ${v('aqi')}` : '-';
		case 'calendar':
			return s.event || s.holiday || (typeof s.workday === 'boolean' ? t(s.workday ? 'v.workday' : 'v.dayoff') : '-');
		case 'timer':
			return s.on ? `${v('remaining')}${s.ends ? ` · ${s.ends.slice(0, 5)}` : ''}` : t('v.off');
		case 'clock':
			return s.on ? s.next || '-' : t('v.off');
		case 'button': {
			const at = d.attrs?.changed?.action;
			return at ? t('v.pressed_ago', { v: f.ago(at) }) : s.action ? t('v.pressed') : t('v.no_press');
		}
		case 'safety':
			return s.alarm ? t('v.alarm') : t(s.armed === false ? 'v.disarmed' : 'v.armed');
		case 'plugguard':
			return typeof s.w === 'number' ? v('w') : '-';
		case 'presence':
			return t('v.rooms_busy', { n: Object.values(s).filter((x) => x === true).length });
	}
	const c = d.caps.find((c) => c.type === 'num' && s[c.id] != null) || d.caps.find((c) => s[c.id] != null);
	return c ? v(c.id) : '-';
}

const SERVICE = new Set(['lqi', 'batlow', 'bat', 'identify', 'countdown', 'action', 'color', 'ct', 'test']);
const ORDER = ['t', 'h', 'w', 'v', 'a', 'kwh', 'co2', 'pm25', 'pm10', 'voc', 'voc_index', 'pa', 'pressure', 'lux', 'p', 'aqi', 'pollen', 'gust', 'wind', 'rain', 'feels'];
const rank = (id) => (ORDER.includes(id) ? ORDER.indexOf(id) : ORDER.length);

export function readings(d) {
	return d.caps
		.filter((c) => !SERVICE.has(c.id) && !c.access.includes('w') && (c.type === 'num' || c.type === 'bool' || c.type === 'enum' || c.type === 'text') && d.state[c.id] != null && d.state[c.id] !== '')
		.sort((a, b) => rank(a.id) - rank(b.id));
}

export const numCaps = (d) => d.caps.filter((c) => c.type === 'num' && !SERVICE.has(c.id));

const dayFmt = new Map();
export function dayKey(ts, tz) {
	const k = tz || '';
	if (!dayFmt.has(k)) dayFmt.set(k, new Intl.DateTimeFormat('en-CA', { timeZone: tz || undefined, year: 'numeric', month: '2-digit', day: '2-digit' }));
	return dayFmt.get(k).format(new Date(ts * 1000));
}

export function counterDelta(points, from = 0) {
	let total = 0;
	let prev = null;
	for (const [ts, v] of points) {
		if (typeof v !== 'number') continue;
		if (prev != null && ts >= from) total += v >= prev ? v - prev : v < prev * 0.5 ? v : 0;
		prev = v;
	}
	return total;
}
