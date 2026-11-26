"""Reference image style and color extractor.

Extracts visual style cues, dominant palette, and lighting from an uploaded
reference photo so that generated designs can match its aesthetic.
"""
import os
import cv2
import numpy as np

COLOR_RANGES = [
    ('pure white', ([0, 0, 200], [180, 40, 255])),
    ('warm beige cream', ([15, 30, 160], [35, 120, 240])),
    ('blush pink', ([155, 30, 140], [175, 160, 255])),
    ('rich red', ([0, 120, 120], [10, 255, 255])),
    ('emerald green', ([35, 80, 80], [85, 255, 220])),
    ('deep blue', ([90, 80, 80], [130, 255, 240])),
    ('warm golden amber', ([15, 120, 150], [30, 255, 255])),
    ('charcoal grey dark', ([0, 0, 20], [180, 40, 90])),
    ('natural wood tone', ([10, 60, 40], [25, 180, 140])),
]


def extract_reference_style(img_path):
    """Return style and color keywords derived from the reference image."""
    if not os.path.isfile(img_path):
        return ''
    try:
        img = cv2.imread(img_path)
        if img is None:
            return ''
        h, w, _ = img.shape
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        total_pixels = float(h * w)

        detected_colors = []
        for name, (lower, upper) in COLOR_RANGES:
            mask = cv2.inRange(hsv, np.array(lower), np.array(upper))
            fraction = np.sum(mask > 0) / total_pixels
            if fraction > 0.10:
                detected_colors.append((fraction, name))

        detected_colors.sort(reverse=True)
        color_text = ', '.join([c[1] for c in detected_colors[:2]])

        v = hsv[:, :, 2]
        brightness = float(np.mean(v))
        s = hsv[:, :, 1]
        saturation = float(np.mean(s))

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 100, 200)
        edge_density = float(np.mean(edges > 0))

        cues = []
        if color_text:
            cues.append(f'matching reference color palette ({color_text})')

        if brightness > 165:
            cues.append('bright airy natural illumination')
        elif brightness < 95:
            cues.append('moody atmospheric ambient lighting')

        if saturation < 45:
            cues.append('soft muted minimalist aesthetic')
        elif saturation > 120:
            cues.append('vibrant rich tones')

        if edge_density > 0.07:
            cues.append('richly textured surfaces')
        else:
            cues.append('clean smooth modern finishes')

        return ', '.join(cues)
    except Exception as exc:
        print('[WARN] Error extracting reference style:', exc)
        return ''
