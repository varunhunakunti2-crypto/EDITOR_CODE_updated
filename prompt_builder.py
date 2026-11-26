"""Turn a short user request plus room details into an SD inpainting prompt.

The user's own words stay first and foremost; the room metadata is appended as
concise context so the model respects the space, style and budget.
"""
MAX_PROMPT_CHARS = 900

ROOM_TYPES = {
    '': 'Choose a room',
    'living_room': 'Living room',
    'bedroom': 'Bedroom',
    'kitchen': 'Kitchen',
    'dining_room': 'Dining room',
    'bathroom': 'Bathroom',
    'home_office': 'Home office',
    'hallway': 'Hallway',
    'other': 'Other',
}

STYLES = {
    '': 'Choose a style',
    'modern': 'Modern',
    'minimalist': 'Minimalist',
    'contemporary': 'Contemporary',
    'traditional': 'Traditional',
    'scandinavian': 'Scandinavian',
    'industrial': 'Industrial',
    'bohemian': 'Boho',
    'rustic': 'Rustic',
    'other': 'Eclectic',
}


def _clean(value):
    return ' '.join(str(value or '').split()).strip()


def _dimension(value, label):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0 or number > 100:
        return None
    return '%s %.2f m' % (label, number)


def build_prompt(user_prompt, room_type='', style='', budget='', preferences='',
                 width_m=None, length_m=None, height_m=None, whole_room=False,
                 detection_notes='', depth_hint='', reference_style=''):
    """Return the final generation prompt.

    ``detection_notes`` is accepted for callers that already have an analysis
    result; it is only used to recover dimensions when none were supplied.
    ``depth_hint`` adds a short relative-depth cue when the optional depth
    assistant is enabled; the raw user prompt is never modified.
    ``reference_style`` appends extracted aesthetic cues from an uploaded reference photo.
    """
    request = _clean(user_prompt)
    if not request:
        raise ValueError('A user prompt is required.')

    parts = [request]
    if whole_room:
        parts.insert(0, 'Redesign the entire visible room, keeping the existing layout')

    ref = _clean(reference_style)
    if ref:
        parts.append('styled after visual reference (' + ref + ')')


    room = _clean(ROOM_TYPES.get(_clean(room_type).lower(), _clean(room_type)))
    if room and room.lower() not in ('any room', 'choose a room', 'other'):
        parts.append('in a ' + room[0].lower() + room[1:])

    style_text = _clean(STYLES.get(_clean(style).lower(), _clean(style)))
    if style_text and style_text.lower() not in ('any style', 'choose a style'):
        parts.append(style_text[0].lower() + style_text[1:] + ' interior style')

    size = [x for x in (
        _dimension(width_m, 'width'), _dimension(length_m, 'length'),
        _dimension(height_m, 'height'),
    ) if x]
    if size:
        parts.append('room dimensions: ' + ', '.join(size))

    budget = _clean(budget)
    if budget:
        parts.append('budget: ' + budget)
    preferences = _clean(preferences)
    if preferences:
        parts.append('preferences: ' + preferences)
    depth_hint = _clean(depth_hint).rstrip('.')
    if depth_hint:
        parts.append('depth cues: ' + depth_hint)

    if len(parts) == 1 and _clean(detection_notes):
        # Keep the prompt readable if all we know is a measurement note.
        parts.append(_clean(detection_notes))

    prompt = '. '.join(parts) + '.'
    if len(prompt) > MAX_PROMPT_CHARS:
        prompt = prompt[:MAX_PROMPT_CHARS].rstrip() + '…'
    return prompt


def describe_room(room_type='', style='', budget='', width_m=None,
                  length_m=None, height_m=None):
    """Short human-readable summary for the result page (no prompt jargon)."""
    bits = []
    for value in (ROOM_TYPES.get(_clean(room_type).lower(), _clean(room_type)),
                  STYLES.get(_clean(style).lower(), _clean(style))):
        value = _clean(value)
        if value and value.lower() not in ('any room', 'any style',
                                           'choose a room', 'choose a style'):
            bits.append(value if value[0].isupper() else value.title())
    dims = [x for x in (
        _dimension(width_m, 'W'), _dimension(length_m, 'L'),
        _dimension(height_m, 'H'),
    ) if x]
    if dims:
        bits.append(' × '.join(dims))
    budget = _clean(budget)
    if budget:
        bits.append('Budget ' + budget)
    return ' · '.join(bits)
