import { capName, value } from '#lib/devices.js';

export const OPS = { eq: '=', ne: '≠', lt: '<', le: '≤', gt: '>', ge: '≥', above: '>', below: '<' };
export const KIND_COLOR = { trig: 'var(--amber)', cond: 'var(--frost)', logic: 'var(--violet)', act: 'var(--ok)', xf: 'var(--ink-2)' };
export const PORT_COLOR = { ev: 'var(--ink-3)', n: 'var(--frost)', sch: 'var(--violet)', b: 'var(--ok)', any: 'var(--line-2)' };

export function blockName(app, def, key) {
	if (def?.name) return def.name[app.lang] ?? def.name.en ?? key;
	const k = `blk.${key}`;
	return app.t.has(k) ? app.t(k) : key;
}

export function duration(app, sec) {
	const s = +sec || 0;
	if (s >= 3600 && s % 3600 === 0) return app.t('d.h', { n: s / 3600 });
	if (s >= 60 && s % 60 === 0) return app.t('d.m', { n: s / 60 });
	return app.t('d.s', { n: s });
}

function val(app, p, v) {
	const d = app.s.devices[p.device];
	if (d && p.cap && (typeof v !== 'object' || v === null)) return value(app, { ...d, state: { [p.cap]: v } }, p.cap);
	if (typeof v === 'boolean') return app.t(v ? 'v.yes' : 'v.no');
	if (typeof v === 'number') return app.f.n(v, Number.isInteger(v) ? 0 : 1);
	return v == null ? '' : String(v);
}

function capText(app, p) {
	const d = app.s.devices[p.device];
	const c = d?.caps.find((x) => x.id === p.cap);
	return c ? capName(app.t, c) : app.t.has(`cap.${p.cap}`) ? app.t(`cap.${p.cap}`) : p.cap;
}

export function values(app, device, vals) {
	return Object.entries(vals || {})
		.map(([k, v]) => (k === 'on' && typeof v === 'boolean' ? val(app, { device, cap: k }, v) : `${capText(app, { device, cap: k })} ${val(app, { device, cap: k }, v)}`))
		.join(', ');
}

export function summary(app, block, p = {}) {
	const { t, s } = app;
	const dev = p.device ? (s.devices[p.device]?.name ?? p.device) : '';
	const parts = [];
	if (dev) parts.push(dev);
	if (p.camera) parts.push(s.devices[p.camera]?.name ?? p.camera);
	if (p.label) parts.push(t.has(`opt.${p.label}`) ? t(`opt.${p.label}`) : p.label);
	if (p.phase === 'end') parts.push(t('opt.end'));
	if (p.cap) {
		let c = capText(app, p);
		if (p.op) c += ` ${OPS[p.op] ?? p.op} ${val(app, p, p.value)}`;
		else if (p.to !== undefined && p.to !== null && p.to !== '') c += ` → ${val(app, p, p.to)}`;
		parts.push(c);
	}
	if (block === 'threshold' && !p.cap) parts.push(`${OPS[p.op] ?? ''} ${p.value ?? ''}`);
	if (p.action) parts.push(p.action);
	if (p.values && typeof p.values === 'object') parts.push(values(app, p.device, p.values));
	if (p.from && p.to && block === 'time_window') parts.push(`${p.from} - ${p.to}`);
	if (p.seconds != null) parts.push(duration(app, p.seconds));
	if (p.timeout != null) parts.push(t('fl.timeout', { v: duration(app, p.timeout) }));
	if (p.minutes != null) parts.push(t('fl.minutes', { n: p.minutes }));
	if (p.cron) parts.push(p.cron);
	if (p.event) parts.push(`${t(`opt.${p.event}`)}${p.offset ? ` ${p.offset > 0 ? '+' : ''}${p.offset} ${t('d.min')}` : ''}`);
	if (p.scene) parts.push(s.scenes.find((x) => x.id === p.scene)?.name ?? p.scene);
	if (p.text) parts.push(`«${p.text}»`);
	if (p.pattern) parts.push(p.pattern);
	if (p.topic) parts.push(p.topic);
	if (p.days) parts.push(p.days.map((d) => t(`wd.${d}`)).join(' '));
	if (p.expr) parts.push(p.expr);
	if (p.count != null && p.window != null) parts.push(t('fl.counter', { n: p.count, m: p.window }));
	for (const k of ['slots', 'before', 'hours'])
		if (p[k] != null && p[k] !== '') parts.push(`${t.has(`prm.${k}`) ? t(`prm.${k}`) : k} ${p[k]}`);
	return parts.filter(Boolean).join(' · ');
}

export function traceText(app, e) {
	const { t } = app;
	const p = { ...(e.p || {}) };
	if (p.cap) p.cap = t.has(`cap.${p.cap}`) ? t(`cap.${p.cap}`) : p.cap;
	for (const k of ['value', 'to', 'target']) if (k in p) p[k] = val(app, {}, p[k]);
	if (p.values) p.values = values(app, null, p.values);
	if (p.seconds != null) p.seconds = duration(app, p.seconds);
	if (p.op) p.op = OPS[p.op] ?? p.op;
	if (p.block) p.block = blockName(app, null, p.block);
	if (e.m === 'dry_ext' && p.text) return t('tr.dry_ext_text', p);
	if (e.m === 'ext_sent' && p.reason) return t('tr.ext_not_sent', { ...p, reason: t.has(`why.${p.reason}`) ? t(`why.${p.reason}`) : p.reason });
	const k = `tr.${e.m}`;
	return t.has(k) ? t(k, p) : `${e.m} ${Object.values(p).join(' ')}`;
}
