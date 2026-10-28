"""Preferences that outlive one run of the GUI: the 고급 옵션 the user last
used, their named presets, and where the save dialog should open.

Deliberately NOT stored next to the exe. A rebuild replaces the whole app
folder, and settings kept inside it would vanish with every update; this file
lives in the per-user config directory instead. HW_SETTINGS_DIR overrides the
location so a check can use a scratch dir and never touch the real one.

Every read and write is best-effort: a missing, unreadable or corrupt file
means "no settings yet", and a failed write is dropped. Preferences are a
convenience — losing them must never stop a conversion.
"""

import json
import os
import sys
from pathlib import Path

DIR_NAME = "handwriting-converter"


def _config_root() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA")
                    or Path.home() / "AppData" / "Local")
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def default_path() -> Path:
    override = os.environ.get("HW_SETTINGS_DIR")
    root = Path(override) if override else _config_root() / DIR_NAME
    return root / "settings.json"


def resolve_open_dir(configured, last_used) -> Path | None:
    """Folder the 파일 선택 dialog opens in: the one the user configured, else
    the one they last opened a file from, else their home folder.

    Never None in practice, and never "" : Qt resolves an empty start path
    against the PROCESS's working directory, which for a double-clicked exe is
    the app folder. That is exactly what the user asked not to see (the same
    fault as the save dialog's, recorded in docs/SOLVED.md)."""
    for candidate in (configured, last_used):
        if candidate:
            folder = Path(candidate)
            if folder.is_dir():
                return folder
    home = Path.home()
    return home if home.is_dir() else None


def resolve_save_dir(configured, last_used, input_path) -> Path | None:
    """Folder the save dialog opens in: the one the user configured, else the
    one they last saved into, else the folder the input file came from."""
    for candidate in (configured, last_used):
        if candidate:
            folder = Path(candidate)
            if folder.is_dir():
                return folder
    if input_path is not None:
        folder = Path(input_path).parent
        if folder.is_dir():
            return folder
    return None


class Settings:
    """The settings file as a plain object. Read on construction, written by
    save()."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else default_path()
        self._data = self._read()

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _section(self, key: str) -> dict:
        value = self._data.get(key)
        return value if isinstance(value, dict) else {}

    @property
    def options(self) -> dict:
        return self._section("options")

    @options.setter
    def options(self, value: dict) -> None:
        self._data["options"] = dict(value)

    @property
    def last_save_dir(self) -> str | None:
        value = self._data.get("last_save_dir")
        return value if isinstance(value, str) else None

    @last_save_dir.setter
    def last_save_dir(self, value) -> None:
        self._data["last_save_dir"] = str(value)

    @property
    def last_open_dir(self) -> str | None:
        value = self._data.get("last_open_dir")
        return value if isinstance(value, str) else None

    @last_open_dir.setter
    def last_open_dir(self, value) -> None:
        self._data["last_open_dir"] = str(value)

    @property
    def open_dir(self) -> str | None:
        """The folder the user configured for 파일 선택, "" / absent when they
        have not."""
        value = self._data.get("open_dir")
        return value if isinstance(value, str) else None

    @open_dir.setter
    def open_dir(self, value) -> None:
        self._data["open_dir"] = str(value)

    @property
    def save_dir(self) -> str | None:
        """The folder the user configured, "" / absent when they have not."""
        value = self._data.get("save_dir")
        return value if isinstance(value, str) else None

    @save_dir.setter
    def save_dir(self, value) -> None:
        self._data["save_dir"] = str(value)

    @property
    def presets(self) -> dict:
        return {name: dict(values)
                for name, values in self._section("presets").items()
                if isinstance(values, dict)}

    def put_preset(self, name: str, values: dict) -> None:
        self._data.setdefault("presets", {})[name] = dict(values)

    def drop_preset(self, name: str) -> None:
        self._section("presets").pop(name, None)

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=1),
                encoding="utf-8")
        except OSError:
            pass
