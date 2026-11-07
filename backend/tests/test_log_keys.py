import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
LEVELS = {"debug", "info", "warning", "error", "exception", "critical"}


def test_log_calls_do_not_pass_reserved_event_key() -> None:
    """Ключ event занят именем записи structlog, вызов с ним падает с TypeError уже после основной работы."""
    bad = []
    for root in (ROOT / "src", ROOT.parent / "mocks" / "valo_mocks", ROOT.parent / "extensions"):
        for f in root.rglob("*.py"):
            for n in ast.walk(ast.parse(f.read_text("utf-8"))):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in LEVELS:
                    if any(k.arg == "event" for k in n.keywords):
                        bad.append(f"{f.relative_to(ROOT.parent)}:{n.lineno}")
    assert bad == []
