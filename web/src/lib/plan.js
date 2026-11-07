export const MARK = 22;
const GAP = 6;
const PAD = 10;

export const clamp01 = (v) => Math.min(1, Math.max(0, Math.round(v * 1000) / 1000));

export function roomDevices(devices, roomId) {
	return devices.filter((d) => d.roomId === roomId && !d.service).sort((a, b) => a.name.localeCompare(b.name));
}

function inside(g, fx, fy) {
	const half = MARK / 2;
	return {
		x: g.x + half + Math.min(1, Math.max(0, fx)) * Math.max(0, g.w - MARK),
		y: g.y + half + Math.min(1, Math.max(0, fy)) * Math.max(0, g.h - MARK)
	};
}

export function toFraction(g, x, y) {
	const half = MARK / 2;
	return [clamp01((x - g.x - half) / Math.max(1, g.w - MARK)), clamp01((y - g.y - half) / Math.max(1, g.h - MARK))];
}

export function markers(g, devs, pos = {}) {
	const free = devs.filter((d) => !Array.isArray(pos[d.id]));
	const perRow = Math.max(1, Math.floor((g.w - PAD * 2 + GAP) / (MARK + GAP)));
	const rows = Math.max(1, Math.floor((g.h - PAD * 2 - 28 + GAP) / (MARK + GAP)));
	const room = perRow * rows;
	const out = [];
	for (const d of devs) {
		const p = pos[d.id];
		if (Array.isArray(p)) out.push({ d, ...inside(g, p[0], p[1]), auto: false });
	}
	free.slice(0, room).forEach((d, i) => {
		const row = Math.floor(i / perRow);
		const col = i % perRow;
		out.push({
			d,
			x: g.x + PAD + MARK / 2 + col * (MARK + GAP),
			y: g.y + g.h - PAD - MARK / 2 - row * (MARK + GAP),
			auto: true
		});
	});
	return { list: out, hidden: Math.max(0, free.length - room) };
}
