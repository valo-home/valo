export const LANGS = ['uk', 'en', 'ru', 'ja', 'fr', 'de', 'es'];

export function pick(cookie, header) {
	if (LANGS.includes(cookie)) return cookie;
	for (const part of (header || '').split(',')) {
		const code = part.split(';')[0].trim().slice(0, 2).toLowerCase();
		if (LANGS.includes(code)) return code;
	}
	return LANGS[0];
}

const rules = {};
const PLURAL = /\{(\w+), plural, ((?:[a-z]+ \{[^{}]*\}\s*)+)\}/g;

function plural(s, p, lang) {
	return s.replace(PLURAL, (m, k, body) => {
		const n = Number(p[k]);
		if (!Number.isFinite(n)) return m;
		const forms = Object.fromEntries([...body.matchAll(/([a-z]+) \{([^{}]*)\}/g)].map((x) => [x[1], x[2]]));
		const r = (rules[lang] ??= new Intl.PluralRules(lang || 'en'));
		return (forms[r.select(n)] ?? forms.other ?? '').replace(/#/g, String(p[k]));
	});
}

export function translator(dict, lang = () => '') {
	const get = typeof dict === 'function' ? dict : () => dict;
	const t = (key, p) => {
		const s = get()[key] ?? key;
		return p ? plural(s, p, lang()).replace(/\{(\w+)\}/g, (m, k) => (p[k] ?? m)) : s;
	};
	t.has = (key) => key in get();
	return t;
}
