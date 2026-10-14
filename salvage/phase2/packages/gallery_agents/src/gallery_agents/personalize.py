from __future__ import annotations

from gallery_agents.contracts import OverlayCue, ViewerProfile

_ES_TRANSLATIONS: dict[str, str] = {
    "Momentum swing": "Cambio de impulso",
    "Key moment": "Momento clave",
    "What-if": "¿Qué pasaría si...?",
}


def _to_spanish(text: str) -> str:
    for en, es in _ES_TRANSLATIONS.items():
        text = text.replace(en, es)
    return text


def personalize_cue(cue: OverlayCue, profile: ViewerProfile) -> OverlayCue:
    payload = dict(cue.payload)

    # Persona shaping
    if profile.persona == "casual":
        # Keep copy shorter and hide dense numbers unless it's a headline metric.
        payload.pop("debug", None)
        if "detail" in payload and isinstance(payload["detail"], str):
            payload["detail"] = payload["detail"].split(".")[0].strip()

    # Favorite player/team emphasis (simple tags for now)
    if profile.favorite_player_id and payload.get("player_id") == profile.favorite_player_id:
        payload["badge"] = "★"
    if profile.favorite_team_id and payload.get("team_id") == profile.favorite_team_id:
        payload["badge"] = "★"

    # Language
    if profile.language == "es":
        for k in ("headline", "detail", "title"):
            if k in payload and isinstance(payload[k], str):
                payload[k] = _to_spanish(payload[k])

    return cue.model_copy(
        update={"payload": payload, "persona": profile.persona, "language": profile.language}
    )
