"""Turn a short user request plus room details into an SD inpainting prompt.

The user's own words stay first and foremost; the room metadata is appended as
concise context so the model respects the space, style and budget.
"""
MAX_PROMPT_CHARS = 900

ROOM_TYPES = {
    '': 'Any room',
    'living_room': 'living room',
    'bedroom': 'bedroom',
    'kitchen': 'kitchen',
    'dining_room': 'dining room',
    'bathroom': 'bathroom',
    'home_office': 'home office',
    'hallway': 'hallway',
    'other': 'room',
}

STYLES = {
    '': 'Any style',
    'modern': 'modern',
    'minimalist': 'minimalist',
    'contemporary': 'contemporary',
    'traditional': 'traditional',
    'scandinavian': 'Scandinavian',
    'industrial': 'industrial',
    'bohemian': 'boho',
    'rustic': 'rustic',
    'other': 'eclectic',
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
                 detection_notes=''):
    """Return the final generation prompt.

    ``detection_notes`` is accepted for callers that already have an analysis
    result; it is only used to recover dimensions when none were supplied.
    """
    request = _clean(user_prompt)
    if not request:
        raise ValueError('A user prompt is required.')

    parts = [request]
    if whole_room:
        parts.insert(0, 'Redesign the entire visible room, keeping the existing layout')

    room = _clean(ROOM_TYPES.get(_clean(room_type).lower(), _clean(room_type)))
    if room and room.lower() != 'any room':
        parts.append('in a ' + room)

    style_text = _clean(STYLES.get(_clean(style).lower(), _clean(style)))
    if style_text and style_text.lower() != 'any style':
        parts.append(style_text + ' interior style')

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
        if value and value.lower() not in ('any room', 'any style'):
            bits.append(value.title())
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
