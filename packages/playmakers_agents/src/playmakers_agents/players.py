from __future__ import annotations

HOME_PLAYERS = (
    "Ellis",
    "Mensah",
    "Costa",
    "Reed",
    "Diallo",
    "Vega",
    "Hale",
    "Silva",
    "Okafor",
    "Marin",
    "Sato",
)
AWAY_PLAYERS = (
    "Bello",
    "Novak",
    "Duarte",
    "Chen",
    "Amari",
    "Solis",
    "Luka",
    "Keita",
    "Santos",
    "Moreau",
    "Ivers",
)


def player_name(player_id: str | None) -> str | None:
    code = (player_id or "").rsplit("_", 1)[-1]
    if len(code) < 2 or code[0] not in "HA" or not code[1:].isdigit():
        return None
    squad = HOME_PLAYERS if code[0] == "H" else AWAY_PLAYERS
    index = int(code[1:]) - 1
    return squad[index] if 0 <= index < len(squad) else None
