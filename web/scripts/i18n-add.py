"""Добавляет ключи во все локали и сохраняет их отсортированными.

python3 scripts/i18n-add.py keys.json, где keys.json это {"ключ": {"ru": "...", "uk": "...", ...}}
"""

import json
import pathlib
import sys

LOCALES = pathlib.Path(__file__).resolve().parent.parent / "src" / "lib" / "i18n" / "locales"


def main() -> None:
    add = json.loads(pathlib.Path(sys.argv[1]).read_text("utf-8"))
    for f in sorted(LOCALES.glob("*.json")):
        lang = f.stem
        data = json.loads(f.read_text("utf-8"))
        for key, texts in add.items():
            text = texts.get(lang) or texts.get("en")
            if text is None:
                sys.exit(f"{key}: нет текста для {lang} и en")
            data[key] = text
        f.write_text(json.dumps(dict(sorted(data.items())), ensure_ascii=False, indent="\t") + "\n", "utf-8")
        print(f"{lang}: {len(data)}")


if __name__ == "__main__":
    main()
