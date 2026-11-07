export function formatter(lang, tz) {
	const nfs = {};
	const nf = (d) => (nfs[d] ??= new Intl.NumberFormat(lang, { minimumFractionDigits: d, maximumFractionDigits: d }));
	const dtf = (o) => new Intl.DateTimeFormat(lang, { timeZone: tz || undefined, ...o });
	const hm = dtf({ hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
	const hms = dtf({ hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' });
	const dm = dtf({ day: 'numeric', month: 'short' });
	const full = dtf({ weekday: 'long', day: 'numeric', month: 'long' });
	const stamp = dtf({ day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
	const head = dtf({ weekday: 'short', day: 'numeric', month: 'short' });
	const rel = new Intl.RelativeTimeFormat(lang, { numeric: 'auto' });
	const dayY = dtf({ weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
	const ymd = dtf({ year: 'numeric', month: 'numeric', day: 'numeric' });
	const mb = new Intl.NumberFormat(lang, { style: 'unit', unit: 'megabyte', maximumFractionDigits: 1 });
	const kb = new Intl.NumberFormat(lang, { style: 'unit', unit: 'kilobyte', maximumFractionDigits: 0 });
	const gb = new Intl.NumberFormat(lang, { style: 'unit', unit: 'gigabyte', maximumFractionDigits: 1 });
	const at = (v) => (v instanceof Date ? v : new Date(typeof v === 'number' && v < 1e12 ? v * 1000 : v));
	return {
		n: (v, d = 1) => (v == null || v === '' || Number.isNaN(+v) ? '-' : nf(d).format(+v)),
		time: (v) => (v ? hm.format(at(v)) : '-'),
		sec: (v) => (v ? hms.format(at(v)) : '-'),
		date: (v) => (v ? dm.format(at(v)) : '-'),
		stamp: (v) => (v ? stamp.format(at(v)) : '-'),
		full: (v) => full.format(v ? at(v) : new Date()),
		day: (v) => dayY.format(v ? at(v) : new Date()),
		week: (v) => {
			const p = Object.fromEntries(ymd.formatToParts(v ? at(v) : new Date()).map((x) => [x.type, x.value]));
			const d = new Date(Date.UTC(+p.year, +p.month - 1, +p.day));
			const wd = d.getUTCDay() || 7;
			d.setUTCDate(d.getUTCDate() + 4 - wd);
			return Math.ceil(((d - Date.UTC(d.getUTCFullYear(), 0, 1)) / 86400000 + 1) / 7);
		},
		head: (v) => head.format(v ? at(v) : new Date()),
		ago: (v) => {
			if (!v) return '-';
			const s = (at(v).getTime() - Date.now()) / 1000;
			for (const [u, k] of [['day', 86400], ['hour', 3600], ['minute', 60]]) if (Math.abs(s) >= k) return rel.format(Math.round(s / k), u);
			return rel.format(Math.round(s), 'second');
		},
		bytes: (v) => (v >= 1073741824 ? gb.format(v / 1073741824) : v >= 1048576 ? mb.format(v / 1048576) : kb.format(v / 1024)).replace(' ', '\u00a0')
	};
}
