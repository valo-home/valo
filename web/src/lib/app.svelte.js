import { getContext, setContext } from 'svelte';
import { io } from 'socket.io-client';
import { api } from '#lib/api.js';
import { formatter } from '#lib/fmt.js';
import { translator } from '#lib/i18n/index.js';

const byId = (list) => Object.fromEntries(list.map((x) => [x.id, x]));

function shape(o) {
	return {
		home: o.home,
		rooms: o.rooms,
		devices: byId(o.devices),
		scenes: o.scenes,
		flows: o.flows,
		notifs: o.notifications,
		events: o.events,
		contrib: o.contrib,
		runs: o.runs,
		env: o.env
	};
}

export const useApp = () => getContext('app');

export function createApp(get) {
	const { overview, me, lang } = get();
	const s = $state({ me, online: false, cmds: {}, toasts: [], ...shape(overview) });
	const t = translator(() => get().dict, () => get().lang);
	const listeners = new Map();
	const rooms = new Set();
	const refs = new Map();
	let sock = null;
	let seq = null;
	let tid = 0;
	let fmt = null;

	const toast = (text, level = 'ok') => {
		const id = ++tid;
		s.toasts.push({ id, text, level });
		setTimeout(() => (s.toasts = s.toasts.filter((x) => x.id !== id)), level === 'crit' ? 7000 : 4000);
	};
	const upsert = (key, d) => {
		const i = s[key].findIndex((x) => x.id === d.id);
		if (i < 0) s[key].push(d);
		else s[key][i] = d;
	};
	const drop = (key, id) => (s[key] = s[key].filter((x) => x.id !== id));
	const contrib = () => api('GET', '/extensions/contributions').then((c) => (s.contrib = c)).catch(() => {});
	const handlers = {
		state(d) {
			const x = s.devices[d.id];
			if (!x) return;
			if (d.s) Object.assign(x.state, d.s);
			if ('a' in d) x.available = d.a;
			if (d.t) x.lastSeen = d.t;
		},
		device: (d) => (s.devices[d.id] = d),
		device_gone: (d) => delete s.devices[d.id],
		cmd(d) {
			if (d.status === 'pending') return void (s.cmds[d.deviceId] = d);
			if (s.cmds[d.deviceId]?.id === d.id) delete s.cmds[d.deviceId];
			if (d.status !== 'ok') toast(t(`cmd.${d.status}`, { name: s.devices[d.deviceId]?.name ?? d.deviceId }), 'crit');
		},
		event: (d) => (s.events = [d, ...s.events.filter((e) => e.id !== d.id)].slice(0, 120)),
		notif: (d) => upsert('notifs', d),
		notif_gone: (d) => drop('notifs', d.id),
		scene: (d) => upsert('scenes', d),
		scene_gone: (d) => drop('scenes', d.id),
		flow: (d) => upsert('flows', d),
		flow_gone: (d) => drop('flows', d.id),
		flow_run(d) {
			const x = s.flows.find((f) => f.id === d.id);
			if (x) Object.assign(x, d);
		},
		home: (d) => (s.home = d),
		room: (d) => upsert('rooms', d),
		room_gone: (d) => drop('rooms', d.id),
		ext: contrib,
		ext_gone: contrib
	};

	async function reload() {
		try {
			Object.assign(s, shape(await api('GET', '/overview')));
		} catch (e) {
			console.error('overview reload failed', e.message);
		}
	}

	async function connect() {
		let first;
		try {
			first = await api('POST', '/auth/ws-ticket');
		} catch (e) {
			console.error('ws ticket failed', e.message);
			setTimeout(connect, 5000);
			return;
		}
		let ticket = first.ticket;
		sock = io(first.url || undefined, {
			transports: ['websocket'],
			auth: (cb) => {
				if (ticket) {
					cb({ ticket });
					ticket = null;
				} else api('POST', '/auth/ws-ticket').then((r) => cb({ ticket: r.ticket })).catch(() => cb({}));
			}
		});
		sock.on('connect', () => {
			s.online = true;
			if (rooms.size) sock.emit('sub', { rooms: [...rooms] });
			if (seq) sock.emit('resume', { seq }, (r) => !r?.ok && reload());
		});
		sock.on('disconnect', () => (s.online = false));
		sock.on('connect_error', (e) => {
			s.online = false;
			console.warn('ws connect error', e.message);
		});
		sock.onAny((ev, msg) => {
			if (msg?.seq) seq = msg.seq;
			handlers[ev]?.(msg?.d);
			listeners.get(ev)?.forEach((fn) => fn(msg?.d));
		});
	}

	return {
		s,
		t,
		lang,
		get f() {
			if (fmt?.tz !== s.home?.timezone) fmt = { tz: s.home?.timezone, ...formatter(lang, s.home?.timezone) };
			return fmt;
		},
		api,
		toast,
		reload,
		connect,
		close: () => sock?.close(),
		on(ev, fn) {
			if (!listeners.has(ev)) listeners.set(ev, new Set());
			listeners.get(ev).add(fn);
			return () => listeners.get(ev).delete(fn);
		},
		sub(list) {
			const fresh = list.filter((r) => !refs.get(r));
			list.forEach((r) => refs.set(r, (refs.get(r) || 0) + 1));
			fresh.forEach((r) => rooms.add(r));
			fresh.length && sock?.connected && sock.emit('sub', { rooms: fresh });
			let done = false;
			return () => {
				if (done) return;
				done = true;
				const gone = list.filter((r) => {
					const n = (refs.get(r) || 1) - 1;
					n ? refs.set(r, n) : refs.delete(r);
					return !n;
				});
				gone.forEach((r) => rooms.delete(r));
				gone.length && sock?.connected && sock.emit('unsub', { rooms: gone });
			};
		},
		async cmd(id, values) {
			try {
				s.cmds[id] = await api('POST', `/devices/${id}/command`, { values });
			} catch (e) {
				toast(e.message, 'crit');
			}
		},
		async run(fn, ok) {
			try {
				const r = await fn();
				if (ok) toast(ok);
				return r ?? true;
			} catch (e) {
				toast(e.message, 'crit');
				return null;
			}
		},
		can: (role) => ({ guest: 0, member: 1, admin: 2, owner: 3 })[s.me.role] >= ({ guest: 0, member: 1, admin: 2, owner: 3 })[role],
		path: (p = '') => `/${lang}${p}`,
		provide() {
			setContext('app', this);
			return this;
		}
	};
}
