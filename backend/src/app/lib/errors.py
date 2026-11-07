import json
import pathlib
from functools import cache

LANGS = ("uk", "en", "ru", "ja", "fr", "de", "es")


class ApplicationError(Exception):
    def __init__(self, code: str, status: int = 400, **params) -> None:
        super().__init__(code)
        self.code, self.status, self.params = code, status, params


@cache
def _texts(name: str) -> dict[str, dict[str, str]]:
    return json.loads((pathlib.Path(__file__).parents[1] / "locales" / f"{name}.json").read_text("utf-8"))


def _render(name: str, code: str, fallback: str, lang: str, params: dict) -> str:
    texts = _texts(name)
    t = texts.get(code) or texts[fallback]
    s = t.get(lang) or t["uk"]
    try:
        return s.format(**params)
    except KeyError, IndexError:
        return s


def message(code: str, lang: str = "uk", **params) -> str:
    return _render("errors", code, "internal", lang, params)


def notice(code: str, lang: str = "uk", **params) -> str:
    return _render("messages", code, "flow_notify", lang, params)


def pick_lang(header: str | None, default: str = "uk") -> str:
    best, q = default, -1.0
    for part in (header or "").split(","):
        tag, _, rest = part.strip().partition(";")
        code = tag.split("-")[0].lower()
        try:
            w = float(rest.split("=")[1]) if rest.strip().startswith("q=") else 1.0
        except ValueError:
            w = 0.0
        if code in LANGS and w > q:
            best, q = code, w
    return best
