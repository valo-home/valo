/** Подгрузка списка порциями по курсору. url(cursor) строит адрес, cursor(item) берет курсор из последней записи */
export function pager(app, url, cursor, size = 50) {
	const st = $state({ items: [], more: false, busy: false, failed: false });
	let gen = 0;
	async function page(after) {
		const g = gen;
		st.busy = true;
		try {
			const rows = await app.api('GET', url(after, size));
			if (g !== gen) return;
			st.items = after == null ? rows : [...st.items, ...rows.filter((r) => !st.items.some((x) => x.id === r.id))];
			st.more = rows.length === size;
			st.failed = false;
		} catch (e) {
			if (g !== gen) return;
			console.warn('list page failed', e?.message);
			st.failed = true;
		} finally {
			if (g === gen) st.busy = false;
		}
	}
	return {
		st,
		reset() {
			gen++;
			st.items = [];
			st.more = false;
			return page(null);
		},
		next() {
			const last = st.items.at(-1);
			return !st.busy && last ? page(cursor(last)) : Promise.resolve();
		},
		push(item) {
			st.items = [item, ...st.items.filter((x) => x.id !== item.id)];
		}
	};
}
