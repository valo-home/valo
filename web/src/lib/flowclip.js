// Буфер блоков редактора сценариев. Общий для всех сценариев в пределах вкладки браузера
export const clip = { nodes: [], edges: [] };

export function uniqueId(base, taken) {
	const root = base.replace(/\d+$/, '') || 'n';
	let id = root;
	for (let i = 1; taken.has(id); i++) id = `${root}${i}`;
	taken.add(id);
	return id;
}

export function copyNodes(nodes, edges, ids) {
	const set = new Set(ids);
	clip.nodes = nodes.filter((n) => set.has(n.id)).map((n) => structuredClone({ id: n.id, position: n.position, data: { block: n.data.block, params: n.data.params } }));
	clip.edges = edges.filter((e) => set.has(e.source) && set.has(e.target)).map((e) => ({ source: e.source, target: e.target, sourceHandle: e.sourceHandle, targetHandle: e.targetHandle }));
	return clip.nodes.length;
}

export function pasteNodes(nodes, offset = 40) {
	const taken = new Set(nodes.map((n) => n.id));
	const map = {};
	const added = clip.nodes.map((n) => {
		map[n.id] = uniqueId(n.id, taken);
		return { id: map[n.id], type: 'block', selected: true, position: { x: n.position.x + offset, y: n.position.y + offset }, data: structuredClone(n.data) };
	});
	const links = clip.edges.map((e) => {
		const source = map[e.source];
		const target = map[e.target];
		return { id: `${source}:${(e.sourceHandle || 'o0').slice(1)}>${target}:${(e.targetHandle || 'i0').slice(1)}`, source, target, sourceHandle: e.sourceHandle, targetHandle: e.targetHandle };
	});
	return { added, links };
}
