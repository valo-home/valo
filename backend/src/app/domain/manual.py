"""Документация продукта: разделы из index.json и страницы <язык>/<страница>.md."""

import json
import pathlib
import re
from functools import lru_cache
from typing import Any

from app.domain import extensions
from app.lib import log
from app.lib.errors import ApplicationError
from app.lib.settings import env

HELP_DIR = pathlib.Path(env("VALO_HELP", "/app/help"))
SLUG = re.compile(r"^[a-z0-9-]{1,40}$")
FALLBACK = ("en", "ru", "uk")
_log = log.get("manual")


@lru_cache(maxsize=4)
def _index(mtime: float) -> dict[str, Any]:
    return json.loads((HELP_DIR / "index.json").read_text("utf-8"))


def index_data() -> dict[str, Any]:
    try:
        return _index((HELP_DIR / "index.json").stat().st_mtime)
    except (OSError, ValueError) as e:
        _log.warning("help_index_unavailable", path=str(HELP_DIR), error=str(e))
        return {"langs": [], "sections": []}


def pick(x: Any, lang: str) -> str:
    if isinstance(x, dict):
        for code in (lang, *FALLBACK):
            if x.get(code):
                return str(x[code])
        return str(next(iter(x.values()), ""))
    return str(x or "")


def find(slug: str, lang: str) -> tuple[pathlib.Path, str] | None:
    if not SLUG.match(slug):
        return None
    for code in (lang, *FALLBACK):
        f = HELP_DIR / code / f"{slug}.md"
        if f.is_file():
            return f, code
    return None


def title_of(text: str, slug: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return slug


def files() -> list[pathlib.Path]:
    return sorted(HELP_DIR.glob("*/*.md")) if HELP_DIR.is_dir() else []


def index(lang: str) -> dict[str, Any]:
    data = index_data()
    sections = []
    for sec in data.get("sections", []):
        pages = []
        for slug in sec.get("pages", []):
            hit = find(slug, lang)
            if hit:
                pages.append({"slug": slug, "title": title_of(hit[0].read_text("utf-8", "replace"), slug)})
        if pages:
            sections.append({"key": sec.get("key", ""), "title": pick(sec.get("title"), lang), "pages": pages})
    exts = []
    for e in extensions.catalog_entries():
        m = e["manifest"]
        if (pathlib.Path(e["path"]) / "docs").is_dir():
            exts.append({"id": m["id"], "name": pick(m.get("name"), lang)})
    exts.sort(key=lambda x: x["name"].lower())
    return {"sections": sections, "extensions": exts}


def page(slug: str, lang: str) -> dict[str, Any]:
    hit = find(slug, lang)
    if hit is None:
        raise ApplicationError("doc_not_found", 404)
    text = hit[0].read_text("utf-8", "replace")
    return {"slug": slug, "lang": hit[1], "title": title_of(text, slug), "text": text}


def search(q: str, lang: str, limit: int = 12) -> list[dict[str, Any]]:
    terms = [t for t in re.findall(r"\w{2,}", q.lower())][:6]
    if not terms:
        return []
    hits = []
    for sec in index_data().get("sections", []):
        for slug in sec.get("pages", []):
            hit = find(slug, lang)
            if not hit:
                continue
            text = hit[0].read_text("utf-8", "replace")
            title = title_of(text, slug)
            best, score = "", 0
            for para in text.split("\n\n"):
                low = para.lower()
                n = sum(low.count(t) for t in terms)
                if n > score and not para.startswith("# "):
                    best, score = para, n
            total = score + 3 * sum(title.lower().count(t) for t in terms)
            if total:
                snippet = re.sub(r"[*`#]|\[([^\]]+)\]\([^)]*\)", r"\1", best).strip()
                hits.append((total, {"slug": slug, "title": title, "text": snippet[:220]}))
    hits.sort(key=lambda x: -x[0])
    return [h for _, h in hits[:limit]]
