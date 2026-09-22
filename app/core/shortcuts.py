"""Centralised keyboard shortcut configuration.

Qt-free by design: parsing, validation, conflict detection and persistence
are pure logic, unit-tested without a display. The Qt binding layer lives in
``app/ui/shortcuts.py``.

Key sequences use Qt *portable* text (``"Ctrl+O"``, ``"Space"``,
``"Shift+Left"``) and a light normalisation makes user-edited files forgiving
(``"ctrl+o"`` == ``"Ctrl+O"``).

The configuration file (created by the user; the settings UI arrives in
Phase 7) lives at ``<config dir>/shortcuts.json``::

    {
      "bindings": {
        "play_pause": ["Space"],
        "seek_back_short": ["Left"],
        "volume_up": ["Up", "Ctrl+Up"]
      }
    }

Actions absent from the file keep their defaults; an empty list explicitly
unbinds an action; unknown action names are ignored (forward compatible).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from app.utils.logging import get_logger

logger = get_logger("core.shortcuts")


class PlayerAction(str, Enum):
    """Every user-triggerable player action.

    The string values are stable identifiers in configuration files — never
    rename them. Actions for future phases are declared now so configuration
    files stay valid; they are simply not bound until implemented.
    """

    OPEN_FILE = "open_file"
    OPEN_URL = "open_url"  # Phase 9 (streams)
    QUIT = "quit"
    PLAY_PAUSE = "play_pause"
    STOP = "stop"
    SEEK_BACK_SHORT = "seek_back_short"
    SEEK_FORWARD_SHORT = "seek_forward_short"
    SEEK_BACK_LONG = "seek_back_long"
    SEEK_FORWARD_LONG = "seek_forward_long"
    VOLUME_UP = "volume_up"
    VOLUME_DOWN = "volume_down"
    MUTE = "mute"
    FULLSCREEN = "fullscreen"
    EXIT_FULLSCREEN = "exit_fullscreen"
    SPEED_UP = "speed_up"
    SPEED_DOWN = "speed_down"
    SPEED_RESET = "speed_reset"
    FRAME_STEP_FORWARD = "frame_step_forward"
    FRAME_STEP_BACKWARD = "frame_step_backward"
    # Reserved for later phases (accepted in config files from day one):
    NEXT_TRACK = "next_track"  # Phase 4 (playlist)
    PREVIOUS_TRACK = "previous_track"  # Phase 4 (playlist)
    SCREENSHOT = "screenshot"  # Phase 8
    TOGGLE_PLAYLIST = "toggle_playlist"  # Phase 4
    SAVE_PLAYLIST = "save_playlist"  # Phase 4
    CYCLE_SUBTITLES = "cycle_subtitles"  # Phase 5
    SUB_DELAY_DOWN = "sub_delay_down"  # Phase 5
    SUB_DELAY_UP = "sub_delay_up"  # Phase 5
    SUB_DELAY_RESET = "sub_delay_reset"  # Phase 5
    MEDIA_INFO = "media_info"  # Phase 6
    SETTINGS = "settings"  # Phase 7
    CYCLE_AUDIO = "cycle_audio"  # Phase 8
    AUDIO_DELAY_DOWN = "audio_delay_down"  # Phase 8
    AUDIO_DELAY_UP = "audio_delay_up"  # Phase 8
    AUDIO_DELAY_RESET = "audio_delay_reset"  # Phase 8


_TOKEN_ALIASES = {
    "ctrl": "Ctrl",
    "shift": "Shift",
    "alt": "Alt",
    "meta": "Meta",
    "del": "Delete",
    "esc": "Escape",
    "space": "Space",
    "ins": "Insert",
    "pgup": "PageUp",
    "pgdown": "PageDown",
}


def normalize_sequence(sequence: str) -> str:
    """Normalise a key sequence string to canonical portable form.

    ``" ctrl+o "`` → ``"Ctrl+O"``, ``"esc"`` → ``"Escape"``. Unknown tokens
    are kept (parsing validity is Qt's business at bind time).

    ``"+"`` is both the separator and a key of its own: a lone ``"+"`` or a
    trailing ``"+"`` (as in ``"Ctrl++"``) means the Plus key and is preserved
    (verified: ``QKeySequence("Plus")`` is invalid, ``QKeySequence("+")`` and
    ``QKeySequence("Ctrl++")`` parse correctly).
    """
    text = sequence.strip()
    if text == "+":
        return "+"
    if not text:
        return ""
    trailing_plus = text.endswith("+")
    parts = [part for part in text.split("+") if part]
    if not parts:
        return "" if not trailing_plus else "+"
    canonical = []
    for part in parts:
        token = _TOKEN_ALIASES.get(part.lower())
        if token is None:
            token = part[:1].upper() + part[1:].lower()
        canonical.append(token)
    if trailing_plus:
        canonical.append("+")
    return "+".join(canonical)


#: Default bindings (normalised). Several sequences per action are allowed.
DEFAULT_BINDINGS: dict[PlayerAction, tuple[str, ...]] = {
    PlayerAction.OPEN_FILE: ("Ctrl+O",),
    PlayerAction.OPEN_URL: ("Ctrl+U",),
    PlayerAction.QUIT: ("Ctrl+Q",),
    PlayerAction.PLAY_PAUSE: ("Space",),
    PlayerAction.STOP: (),
    PlayerAction.SEEK_BACK_SHORT: ("Left",),
    PlayerAction.SEEK_FORWARD_SHORT: ("Right",),
    PlayerAction.SEEK_BACK_LONG: ("Shift+Left",),
    PlayerAction.SEEK_FORWARD_LONG: ("Shift+Right",),
    PlayerAction.VOLUME_UP: ("Up",),
    PlayerAction.VOLUME_DOWN: ("Down",),
    PlayerAction.MUTE: ("M",),
    PlayerAction.FULLSCREEN: ("F",),
    PlayerAction.EXIT_FULLSCREEN: ("Escape",),
    PlayerAction.SPEED_UP: ("]",),
    PlayerAction.SPEED_DOWN: ("[",),
    PlayerAction.SPEED_RESET: ("Backspace",),
    PlayerAction.FRAME_STEP_FORWARD: (".",),
    PlayerAction.FRAME_STEP_BACKWARD: (",",),
    PlayerAction.NEXT_TRACK: ("N",),
    PlayerAction.PREVIOUS_TRACK: ("P",),
    PlayerAction.SCREENSHOT: ("S",),
    PlayerAction.TOGGLE_PLAYLIST: ("Ctrl+L",),
    PlayerAction.SAVE_PLAYLIST: ("Ctrl+S",),
    PlayerAction.CYCLE_SUBTITLES: ("J",),
    PlayerAction.SUB_DELAY_DOWN: ("Z",),
    PlayerAction.SUB_DELAY_UP: ("X",),
    PlayerAction.SUB_DELAY_RESET: ("Shift+Z",),
    PlayerAction.MEDIA_INFO: ("Ctrl+I",),
    PlayerAction.SETTINGS: ("Ctrl+,",),
    PlayerAction.CYCLE_AUDIO: ("B",),
    PlayerAction.AUDIO_DELAY_DOWN: ("-",),
    PlayerAction.AUDIO_DELAY_UP: ("+", "="),
    PlayerAction.AUDIO_DELAY_RESET: ("Shift+-",),
}


@dataclass(frozen=True)
class ShortcutConfig:
    """A resolved set of action → key-sequence bindings."""

    bindings: dict[PlayerAction, tuple[str, ...]]

    @classmethod
    def defaults(cls) -> ShortcutConfig:
        # Normalised once here so the declared table can stay human-readable
        # (e.g. "+" for the Plus key) while every consumer sees canonical form.
        return cls(
            {
                action: tuple(normalize_sequence(s) for s in sequences)
                for action, sequences in DEFAULT_BINDINGS.items()
            }
        )

    def sequences(self, action: PlayerAction) -> tuple[str, ...]:
        return self.bindings.get(action, ())

    def conflicts(self) -> dict[str, list[PlayerAction]]:
        """Map each sequence owned by more than one entry to its owners.

        This covers both different actions sharing a key and one action
        binding the same key twice. An empty dict means the config is sane.
        """
        owners: dict[str, list[PlayerAction]] = {}
        for action, sequences in self.bindings.items():
            for raw in sequences:
                normalized = normalize_sequence(raw)
                if normalized:
                    owners.setdefault(normalized, []).append(action)
        return {sequence: actions for sequence, actions in owners.items() if len(actions) > 1}

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> ShortcutConfig:
        """Build a config from a parsed mapping, filling defaults.

        Accepts either ``{"bindings": {...}}`` or a flat ``{action: [...]}``.
        Unknown actions and malformed entries are skipped with a warning.
        """
        merged: dict[PlayerAction, tuple[str, ...]] = dict(cls.defaults().bindings)
        raw = data.get("bindings", data) if isinstance(data, Mapping) else {}
        if not isinstance(raw, Mapping):
            # ValueError (not TypeError): untrusted-data validation,
            # caught by load() which falls back to defaults.
            raise ValueError("bindings must be an object")  # noqa: TRY004
        for key, value in raw.items():
            try:
                action = PlayerAction(key)
            except ValueError:
                logger.warning("ignoring unknown shortcut action %r", key)
                continue
            if isinstance(value, str):
                value = [value]
            if not isinstance(value, (list, tuple)):
                logger.warning("ignoring malformed binding for %r", key)
                continue
            sequences = tuple(
                normalize_sequence(item) for item in value if isinstance(item, str) and item.strip()
            )
            merged[action] = sequences
        return cls(merged)

    def to_dict(self) -> dict[str, list[str]]:
        """Serialise all actions — including explicit unbinds (empty lists),
        so a save/load round trip is lossless."""
        return {action.value: list(sequences) for action, sequences in self.bindings.items()}

    @classmethod
    def load(cls, path: Path) -> ShortcutConfig:
        """Load from disk; any problem falls back to the defaults.

        A missing file is normal (first run) and is not logged as a warning.
        """
        try:
            if not path.exists():
                return cls.defaults()
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("root must be a JSON object")  # noqa: TRY004 — see from_dict
            config = cls.from_dict(data.get("bindings", {}))
        except (OSError, json.JSONDecodeError, ValueError):
            logger.warning("shortcut config %s unreadable; using defaults", path, exc_info=True)
            return cls.defaults()
        for sequence, actions in config.conflicts().items():
            logger.warning("shortcut conflict in %s: %s used by %s", path, sequence, actions)
        return config
