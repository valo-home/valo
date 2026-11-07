<script>
	import { useApp } from '#lib/app.svelte.js';

	let { text = '' } = $props();
	const app = useApp();
	const href = (u) => (u.startsWith('/') && !u.startsWith('//') ? app.path(u) : /^https?:\/\//.test(u) ? u : '');

	function inline(s) {
		const out = [];
		const re = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\))/g;
		let last = 0;
		for (const m of s.matchAll(re)) {
			if (m.index > last) out.push({ t: 'text', v: s.slice(last, m.index) });
			const a = m[0].match(/^\[([^\]]+)\]\(([^)\s]+)\)$/);
			if (a) out.push(href(a[2]) ? { t: 'a', v: a[1], u: href(a[2]), ext: !a[2].startsWith('/') } : { t: 'text', v: a[1] });
			else out.push(m[0].startsWith('**') ? { t: 'b', v: m[0].slice(2, -2) } : { t: 'code', v: m[0].slice(1, -1) });
			last = m.index + m[0].length;
		}
		if (last < s.length) out.push({ t: 'text', v: s.slice(last) });
		return out;
	}

	const blocks = $derived.by(() => {
		const res = [];
		let list = null;
		let para = [];
		let code = null;
		const flush = () => {
			if (para.length) res.push({ t: 'p', v: inline(para.join(' ')) });
			para = [];
		};
		for (const raw of String(text).split('\n')) {
			if (raw.trimStart().startsWith('```')) {
				if (code) {
					res.push({ t: 'pre', v: code.join('\n') });
					code = null;
				} else {
					flush();
					list = null;
					code = [];
				}
				continue;
			}
			if (code) {
				code.push(raw);
				continue;
			}
			const line = raw.trimEnd();
			const h = line.match(/^(#{1,3})\s+(.*)$/);
			const ul = line.match(/^\s*[-*]\s+(.*)$/);
			const ol = line.match(/^\s*\d+\.\s+(.*)$/);
			const tr = line.trim().startsWith('|') && line.trim().endsWith('|') ? line.trim().slice(1, -1).split('|').map((c) => c.trim()) : null;
			if (tr) {
				flush();
				if (!list || list.t !== 'table') res.push((list = { t: 'table', head: null, rows: [] }));
				if (tr.every((c) => /^:?-{2,}:?$/.test(c))) continue;
				if (!list.head && !list.rows.length) list.head = tr.map(inline);
				else list.rows.push(tr.map(inline));
			} else if (h) {
				flush();
				list = null;
				res.push({ t: `h${h[1].length}`, v: inline(h[2]) });
			} else if (ul || ol) {
				flush();
				const kind = ul ? 'ul' : 'ol';
				if (!list || list.t !== kind) res.push((list = { t: kind, items: [] }));
				list.items.push(inline((ul || ol)[1]));
			} else if (!line.trim()) {
				flush();
				list = null;
			} else {
				list = null;
				para.push(line.trim());
			}
		}
		if (code) res.push({ t: 'pre', v: code.join('\n') });
		flush();
		return res;
	});
</script>

{#snippet spans(parts)}{#each parts as x}{#if x.t === 'b'}<b>{x.v}</b>{:else if x.t === 'a'}<a href={x.u} target={x.ext ? '_blank' : undefined} rel={x.ext ? 'noopener noreferrer' : undefined}>{x.v}</a>{:else if x.t === 'code'}<code class="mono">{x.v}</code>{:else}{x.v}{/if}{/each}{/snippet}

<div class="md">
	{#each blocks as b, i (i)}
		{#if b.t === 'h1'}<h2>{@render spans(b.v)}</h2>
		{:else if b.t === 'h2'}<h3>{@render spans(b.v)}</h3>
		{:else if b.t === 'h3'}<h4>{@render spans(b.v)}</h4>
		{:else if b.t === 'ul'}<ul>{#each b.items as it}<li>{@render spans(it)}</li>{/each}</ul>
		{:else if b.t === 'ol'}<ol>{#each b.items as it}<li>{@render spans(it)}</li>{/each}</ol>
		{:else if b.t === 'pre'}<pre class="mono">{b.v}</pre>
		{:else if b.t === 'table'}<div class="mdt"><table>{#if b.head}<thead><tr>{#each b.head as c}<th>{@render spans(c)}</th>{/each}</tr></thead>{/if}<tbody>{#each b.rows as r}<tr>{#each r as c}<td>{@render spans(c)}</td>{/each}</tr>{/each}</tbody></table></div>
		{:else}<p>{@render spans(b.v)}</p>{/if}
	{/each}
</div>

<style>
	.md {
		display: grid;
		gap: 8px;
		line-height: 1.55;
	}
	.md :global(h3) {
		margin: 10px 0 0;
		font-size: 15px;
	}
	.md :global(h4) {
		margin: 6px 0 0;
		font-size: 14px;
	}
	.md :global(p),
	.md :global(ul),
	.md :global(ol) {
		margin: 0;
	}
	.md :global(ul),
	.md :global(ol) {
		padding-left: 20px;
		display: grid;
		gap: 4px;
	}
	.mdt {
		overflow-x: auto;
		border: 1px solid var(--line);
		border-radius: 10px;
	}
	.mdt table {
		width: 100%;
		border-collapse: collapse;
		font-size: 13px;
	}
	.mdt :global(th),
	.mdt :global(td) {
		text-align: left;
		vertical-align: top;
		padding: 7px 10px;
		border-bottom: 1px solid var(--line);
	}
	.mdt :global(tr:last-child td) {
		border-bottom: 0;
	}
	.mdt :global(th) {
		background: var(--raise);
		font-weight: 600;
	}
	.md :global(pre) {
		margin: 0;
		padding: 10px 12px;
		border-radius: 8px;
		background: var(--sunk);
		border: 1px solid var(--line);
		font-size: 12px;
		overflow-x: auto;
		white-space: pre;
	}
	.md :global(code) {
		font-size: 12px;
		padding: 1px 5px;
		border-radius: 5px;
		background: var(--sunk);
		border: 1px solid var(--line);
		overflow-wrap: anywhere;
	}
</style>
