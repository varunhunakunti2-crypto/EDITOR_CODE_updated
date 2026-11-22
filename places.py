"""Nearby places to buy an item, suggested by Gemini."""
import json
import re
from urllib.parse import quote_plus

import config

_models = {}


def _get_model(name):
    import google.generativeai as genai  # imported lazily so the app still starts without it
    if not _models:
        genai.configure(api_key=config.GEMINI_API_KEY)
    if name not in _models:
        # Gemini 3.x spends part of the token budget on internal "thinking".
        # A small cap used to leave no tokens for the actual JSON reply.
        _models[name] = genai.GenerativeModel(
            name,
            generation_config=genai.types.GenerationConfig(max_output_tokens=1024),
        )
    return _models[name]


def maps_link(query):
    return "https://www.google.com/maps/search/?api=1&query=" + quote_plus(query)


def _parse_json(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    try:
        return json.loads(text)
    except ValueError:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            return json.loads(match.group(0))
        raise


def _clean(data, location):
    item = str(data.get("item") or "").strip()[:80]
    places = []
    for p in (data.get("places") or [])[:6]:
        if not isinstance(p, dict) or not p.get("name"):
            continue
        name = str(p["name"]).strip()[:100]
        area = str(p.get("area") or "").strip()[:100]
        places.append({
            "name": name,
            "type": str(p.get("type") or "").strip()[:60],
            "area": area,
            "why": str(p.get("why") or "").strip()[:200],
            "map_url": maps_link(f"{name} {area} {location}".strip()),
        })
    return item, places


def find_nearby_places(prompt, location):
    """Return {'item', 'places', 'search_url', 'error'}. Never raises."""
    location = (location or "").strip()
    result = {"item": "", "places": [], "error": None, "location": location,
              "search_url": None}
    if not location:
        result["error"] = "No location given, so no nearby stores were searched."
        return result
    if not config.GEMINI_API_KEY:
        result["error"] = "GEMINI_API_KEY is not set."
        result["search_url"] = maps_link(f"{prompt} shop near {location}")
        return result

    question = (
        "A user is decorating a room with this request: \"" + prompt + "\".\n"
        "1. Identify the single physical item they want to buy (2-4 words).\n"
        "2. Suggest up to 5 real, well-known stores or markets near \"" + location + "\" "
        "where that item can be purchased. Only name places you are confident exist; "
        "prefer established chains or well-known markets over guessing small shops.\n"
        "Reply with ONLY JSON in this exact shape, no markdown:\n"
        '{"item": "...", "places": [{"name": "...", "type": "store type", '
        '"area": "neighbourhood or street", "why": "one short sentence"}]}'
    )

    names = [config.GEMINI_MODEL] + [m for m in config.GEMINI_FALLBACK_MODELS
                                     if m != config.GEMINI_MODEL]
    for name in names:
        try:
            # Single-turn generation with a hard timeout: the chat API can hang
            # indefinitely on a slow Gemini 3.x response.
            response = _get_model(name).generate_content(
                question, request_options={"timeout": config.GEMINI_TIMEOUT}
            )
            item, places = _clean(_parse_json(response.text), location)
            result.update(item=item, places=places)
            break
        except Exception as exc:  # network, quota, bad model name, blocked reply, bad JSON
            print(f"Gemini model {name} failed: {exc}")
    else:
        result["error"] = "Gemini could not be reached right now. Use the map search below."

    result["search_url"] = maps_link(f"{result['item'] or prompt} shop near {location}")
    if not result["places"] and not result["error"]:
        result["error"] = "Gemini returned no stores. Use the map search below."
    return result
