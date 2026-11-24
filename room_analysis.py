"""Measure a room from a single photo using OpenCV.

The detector finds wall/ceiling/floor boundaries with Canny edges and Hough
line segments, converts a pixel span into metres using a known reference
length (a door is about 2 m), and writes an annotated overlay image.

Command line example::

    python room_analysis.py sample.jpg --reference-length 2 --reference-pixels 180

Python API::

    from room_analysis import analyze_room
    result = analyze_room('sample.jpg', reference_length_m=2.0,
                          reference_pixels=180, manual={'height_m': 2.8})
"""
import argparse
import json
import os
import uuid

import cv2
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUTPUT_DIR = os.path.join(BASE_DIR, 'static', 'uploads', 'analysis')
DEFAULT_REFERENCE_M = 2.0  # a typical interior door
DEFAULT_CEILING_M = 2.8

# Confidence is based on how many independent signals were found.
PLAUSIBLE = {
    'width_m': (1.5, 15.0),
    'length_m': (1.5, 20.0),
    'height_m': (2.0, 4.5),
}


def _load_image(path, max_size):
    """Return the resized working image plus original size and scale factor."""
    image = cv2.imread(str(path))
    if image is None:
        raise ValueError('Could not read image: %s' % path)
    height, width = image.shape[:2]
    scale = 1.0
    if max(width, height) > max_size:
        scale = max_size / float(max(width, height))
        image = cv2.resize(image, None, fx=scale, fy=scale,
                           interpolation=cv2.INTER_AREA)
    return image, width, height, scale


def _edge_map(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.createCLAHE(2.0, (8, 8)).apply(gray)
    gray = cv2.bilateralFilter(gray, 7, 50, 50)
    edges = cv2.Canny(gray, 60, 160)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    return cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)


def _hough_segments(edges, width, height):
    """Detect long line segments and label them horizontal / vertical / other."""
    smallest = min(width, height)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180,
        threshold=max(30, int(smallest * 0.075)),
        minLineLength=max(35, int(smallest * 0.14)),
        maxLineGap=max(8, int(smallest * 0.025)),
    )
    segments = []
    if lines is None:
        return segments
    # OpenCV 3/4 return (N, 1, 4); OpenCV 5 returns (N, 4).
    lines = np.asarray(lines).reshape(-1, 4)
    for x1, y1, x2, y2 in lines:
        x1, y1, x2, y2 = [float(v) for v in (x1, y1, x2, y2)]
        dx, dy = x2 - x1, y2 - y1
        length = float(np.hypot(dx, dy))
        if length < 1:
            continue
        angle = np.degrees(np.arctan2(dy, dx))
        if angle > 90:
            angle -= 180
        elif angle < -90:
            angle += 180
        if abs(angle) <= 10:
            orientation = 'horizontal'
        elif abs(abs(angle) - 90) <= 10:
            orientation = 'vertical'
        else:
            orientation = 'diagonal'
        segments.append({
            'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2,
            'x': (x1 + x2) / 2.0, 'y': (y1 + y2) / 2.0,
            'length': length, 'angle': round(float(angle), 1),
            'orientation': orientation,
        })
    return segments


def _cluster(segments, axis, tolerance):
    """Group parallel lines by position; weight each group by segment length."""
    items = sorted((s for s in segments if s['orientation'] != 'diagonal'),
                   key=lambda s: s[axis])
    groups = []
    for seg in items:
        value = seg[axis]
        if groups and value - groups[-1]['start'] <= tolerance:
            groups[-1]['items'].append(seg)
        else:
            groups.append({'start': value, 'items': [seg]})
    result = []
    for group in groups:
        weight = sum(s['length'] for s in group['items'])
        centre = sum(s[axis] * s['length'] for s in group['items']) / weight
        result.append({'position': centre, 'weight': weight,
                       'count': len(group['items']), 'items': group['items']})
    return result


def _best_pair(clusters, low_limit, high_limit):
    """Pick the two most separated boundaries on opposite halves of the image."""
    low = [c for c in clusters if c['position'] < low_limit]
    high = [c for c in clusters if c['position'] > high_limit]
    if not low or not high:
        if len(clusters) < 2:
            return None
        ordered = sorted(clusters, key=lambda c: c['position'])
        return ordered[0], ordered[-1], False
    best = max(((a, b) for a in low for b in high),
               key=lambda pair: (pair[1]['position'] - pair[0]['position'])
               + 0.05 * (pair[0]['weight'] + pair[1]['weight']))
    return best[0], best[1], True


def _auto_reference(segments, floor_y, height):
    """Guess the door: a medium-tall vertical line ending near the floor."""
    candidates = [s for s in segments if s['orientation'] == 'vertical'
                  and 0.12 * height <= s['length'] <= 0.7 * height]
    if not candidates:
        return None
    horizontals = [s for s in segments if s['orientation'] == 'horizontal']

    def score(seg):
        ratio = seg['length'] / float(height)
        value = 1.0 - abs(ratio - 0.33) / 0.33
        bottom = max(seg['y1'], seg['y2'])
        top = min(seg['y1'], seg['y2'])
        value += 0.5 * (1.0 - min(1.0, abs(bottom - floor_y) / float(height)))
        if any(abs(h['y'] - top) < 0.025 * height for h in horizontals):
            value += 0.3
        return value

    return max(candidates, key=score)


def _draw_overlay(image, segments, vertical_pair, horizontal_pair,
                  reference_segment, result):
    canvas = image.copy()
    h, w = canvas.shape[:2]

    for seg in segments:
        if seg['orientation'] == 'vertical':
            colour, thickness = (0, 220, 0), 1
        elif seg['orientation'] == 'horizontal':
            colour, thickness = (0, 220, 255), 1
        else:
            colour, thickness = (130, 130, 130), 1
        cv2.line(canvas, (int(seg['x1']), int(seg['y1'])),
                 (int(seg['x2']), int(seg['y2'])), colour, thickness)

    if vertical_pair:
        for cluster in vertical_pair[:2]:
            x = int(cluster['position'])
            cv2.line(canvas, (x, 0), (x, h), (0, 0, 255), 3)
    if horizontal_pair:
        for cluster in horizontal_pair[:2]:
            y = int(cluster['position'])
            cv2.line(canvas, (0, y), (w, y), (255, 0, 255), 3)
    if vertical_pair and horizontal_pair:
        for x_cluster in vertical_pair[:2]:
            for y_cluster in horizontal_pair[:2]:
                cv2.circle(canvas, (int(x_cluster['position']),
                                    int(y_cluster['position'])), 6, (0, 0, 255), -1)
    if reference_segment:
        cv2.line(canvas, (int(reference_segment['x1']), int(reference_segment['y1'])),
                 (int(reference_segment['x2']), int(reference_segment['y2'])),
                 (0, 255, 255), 4)

    lines = [
        'Room: W %.2f m x L %.2f m x H %.2f m' % (
            result['width_m'], result['length_m'], result['height_m']),
        'Confidence: %s | Reference: %.2f m = %d px (%s)' % (
            result['confidence'], result['reference']['length_m'],
            round(result['reference']['pixels']), result['reference']['source']),
    ]
    note = result['note']
    while note:
        lines.append(note[:72])
        note = note[72:].strip()

    overlay = canvas.copy()
    box_height = 14 + 22 * len(lines)
    cv2.rectangle(overlay, (8, 8), (min(w - 8, 560), box_height), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.85, canvas, 0.15, 0, canvas)
    for index, text in enumerate(lines):
        cv2.putText(canvas, text, (18, 30 + index * 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1,
                    cv2.LINE_AA)

    output_dir = result.get('_output_dir', DEFAULT_OUTPUT_DIR)
    os.makedirs(output_dir, exist_ok=True)
    filename = 'analysis_' + uuid.uuid4().hex + '.png'
    path = os.path.join(output_dir, filename)
    if not cv2.imwrite(path, canvas):
        raise RuntimeError('Could not write overlay image: %s' % path)
    try:
        return os.path.relpath(path, BASE_DIR).replace('\\', '/')
    except ValueError:
        return path


def analyze_room(image_path, reference_length_m=DEFAULT_REFERENCE_M,
                 reference_pixels=None, manual=None, output_dir=None,
                 max_size=1400):
    """Measure a room and return dimensions, confidence and an overlay path.

    ``reference_pixels`` is the on-screen length of the reference object in the
    original image (e.g. a door that is about 2 m tall). If omitted, a door-like
    vertical segment is guessed and confidence is reduced.

    ``manual`` may contain any of ``width_m``, ``length_m``, ``height_m``,
    ``reference_pixels`` and ``reference_length_m`` to override detection.
    """
    work, original_w, original_h, scale = _load_image(image_path, max_size)
    height, width = work.shape[:2]
    output_dir = output_dir or DEFAULT_OUTPUT_DIR
    manual = dict(manual or {})
    notes = []

    edges = _edge_map(work)
    segments = _hough_segments(edges, width, height)
    vertical_lines = [s for s in segments if s['orientation'] == 'vertical']
    horizontal_lines = [s for s in segments if s['orientation'] == 'horizontal']
    verticals = _cluster(vertical_lines, 'x', max(8, 0.02 * width))
    horizontals = _cluster(horizontal_lines, 'y', max(8, 0.02 * height))
    vertical_pair = _best_pair(verticals, 0.45 * width, 0.55 * width)
    horizontal_pair = _best_pair(horizontals, 0.42 * height, 0.55 * height)

    floor_y = horizontal_pair[1]['position'] if horizontal_pair else height * 0.8
    ref_segment = _auto_reference(segments, floor_y, height)

    # Reference length / pixel span (pixel values are given for the source image).
    ref_m = float(manual.get('reference_length_m', reference_length_m))
    ref_source = 'manual'
    if 'reference_pixels' in manual:
        ref_px = float(manual['reference_pixels']) * scale
    elif reference_pixels is not None:
        ref_px = float(reference_pixels) * scale
    elif ref_segment:
        ref_px = float(ref_segment['length'])
        ref_source = 'auto door guess'
        notes.append('Reference length was guessed from a door-like edge; '
                     'supply its pixel height for a reliable scale.')
    else:
        ref_px = float(height)
        ref_m = DEFAULT_CEILING_M
        ref_source = 'assumed ceiling height'
        notes.append('No reference edge found; assumed a %.1f m ceiling.' % DEFAULT_CEILING_M)

    if ref_px <= 0 or ref_m <= 0:
        raise ValueError('Reference length and pixel span must be positive.')
    metres_per_pixel = ref_m / ref_px

    # Pixel spans -> metres.
    if vertical_pair:
        width_px = abs(vertical_pair[1]['position'] - vertical_pair[0]['position'])
        width_m = width_px * metres_per_pixel
    else:
        width_px = None
        width_m = max(3.0, ref_m * 2.2)
        notes.append('Wall boundaries unclear; width is a rough estimate.')

    if horizontal_pair:
        height_px = abs(horizontal_pair[1]['position'] - horizontal_pair[0]['position'])
        height_m = height_px * metres_per_pixel
    else:
        height_px = None
        height_m = DEFAULT_CEILING_M
        notes.append('Ceiling/floor lines unclear; using a %.1f m ceiling estimate.'
                     % DEFAULT_CEILING_M)

    length_m = width_m * 1.3
    notes.append('Length (depth) is estimated from typical room proportions; '
                 'override it if you know the room plan.')

    overridden = [key for key in ('width_m', 'length_m', 'height_m') if key in manual]
    if 'width_m' in manual:
        width_m = float(manual['width_m'])
    if 'length_m' in manual:
        length_m = float(manual['length_m'])
    if 'height_m' in manual:
        height_m = float(manual['height_m'])
    if overridden:
        notes.append('Manual override applied to: %s.' % ', '.join(overridden))

    # Confidence from the independent signals available.
    signals = sum([bool(vertical_pair), bool(horizontal_pair),
                   ref_source == 'manual', all(
                       PLAUSIBLE[key][0] <= value <= PLAUSIBLE[key][1]
                       for key, value in (('width_m', width_m),
                                          ('length_m', length_m),
                                          ('height_m', height_m)))])
    if len(overridden) == 3:
        confidence = 'manual'
    elif signals >= 3:
        confidence = 'high'
    elif signals >= 1:
        confidence = 'medium'
    else:
        confidence = 'low'
    if signals < 4 and 'plausible' not in ' '.join(notes):
        notes.append('Check the result against a known measurement before ordering.')

    result = {
        'width_m': round(width_m, 2),
        'length_m': round(length_m, 2),
        'height_m': round(height_m, 2),
        'confidence': confidence,
        'note': ' '.join(notes),
        'reference': {
            'length_m': round(ref_m, 2),
            'pixels': round(ref_px / scale, 1),
            'source': ref_source,
        },
        'detected': {
            'segments': len(segments),
            'verticals': len(verticals),
            'horizontals': len(horizontals),
            'width_px': round(width_px, 1) if width_px else None,
            'height_px': round(height_px, 1) if height_px else None,
            'corners': [
                [round(v['position'] / scale, 1), round(hh['position'] / scale, 1)]
                for v in (vertical_pair[:2] if vertical_pair else [])
                for hh in (horizontal_pair[:2] if horizontal_pair else [])
            ],
        },
        'image_size': [original_w, original_h],
        '_output_dir': output_dir,
    }
    result['overlay_path'] = _draw_overlay(work, segments, vertical_pair,
                                           horizontal_pair, ref_segment, result)
    result.pop('_output_dir', None)
    return result


def main():
    parser = argparse.ArgumentParser(description='Measure a room from a photo.')
    parser.add_argument('image', help='path to a room photo')
    parser.add_argument('--reference-length', type=float, default=DEFAULT_REFERENCE_M,
                        help='known length of the reference object in metres (default 2)')
    parser.add_argument('--reference-pixels', type=float,
                        help='pixel length of the reference object in the original image')
    parser.add_argument('--width', type=float, help='manual width in metres')
    parser.add_argument('--length', type=float, help='manual length in metres')
    parser.add_argument('--height', type=float, help='manual height in metres')
    parser.add_argument('--output-dir', default=DEFAULT_OUTPUT_DIR,
                        help='where to write the annotated overlay image')
    args = parser.parse_args()

    manual = {key: getattr(args, key) for key in ('width', 'length', 'height')
              if getattr(args, key) is not None}
    result = analyze_room(args.image, args.reference_length, args.reference_pixels,
                          manual, args.output_dir)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
