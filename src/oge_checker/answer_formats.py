import re


TYPES = {
    'mixed': 'Любой текст', 'digits': 'Последовательность цифр',
    'integer': 'Целое число', 'decimal': 'Число с разделителем',
    'cyrillic': 'Кириллица', 'latin': 'Латиница', 'letters': 'Буквы',
}
PATTERNS = {
    'digits': r'[0-9]+', 'integer': r'-?[0-9]+',
    'decimal': r'-?[0-9]+(?:[,.][0-9]+)?',
    'cyrillic': r'[А-Яа-яЁё]+', 'latin': r'[A-Za-z]+',
    'letters': r'[A-Za-zА-Яа-яЁё]+',
}


def validate_format(spec):
    if not isinstance(spec, dict) or spec.get('type', 'mixed') not in TYPES:
        raise ValueError('Неизвестный тип ответа')
    for name in ('min_length', 'max_length'):
        if type(spec.get(name, 0)) is not int or not 0 <= spec.get(name, 0) <= 256:
            raise ValueError('Длина ответа должна быть от 0 до 256')
    if spec.get('max_length') and spec.get('min_length', 0) > spec['max_length']:
        raise ValueError('Минимальная длина больше максимальной')
    return spec


def format_error(text, spec=None):
    spec = spec or {}
    value = ''.join(text.split()).replace('−', '-')
    if not value:
        return ''
    kind = spec.get('type', 'mixed')
    if kind in PATTERNS and not re.fullmatch(PATTERNS[kind], value):
        return f'Ожидается: {TYPES[kind]}'
    if len(value) < spec.get('min_length', 0):
        return f"Минимальная длина: {spec['min_length']}"
    if spec.get('max_length') and len(value) > spec['max_length']:
        return f"Максимальная длина: {spec['max_length']}"
    return ''


def constrained_read(base, cleaned, spec, read, numeric=None):
    if not spec or not format_error(base, spec):
        return base
    import cv2
    from collections import Counter
    values = []
    for image in (cleaned, cv2.resize(cleaned, None, fx=.7, fy=1),
                  cv2.erode(cleaned, cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)))):
        raw, _ = read(image)
        value = ''.join(raw.split()).replace('−', '-')
        if spec.get('type') == 'cyrillic':
            from .personal import russian
            value = russian(value)
        if value and not format_error(value, spec):
            values.append(value)
    if numeric and spec.get('type') in ('digits', 'integer', 'decimal'):
        value = numeric.get('candidate', '')
        support = numeric.get('agreements', [])
        distances = numeric.get('distances', [])
        if value and len(support) == len(distances) == len(value) and all(a >= .8 and d <= 2 for a, d in zip(support, distances)) and not format_error(value, spec):
            values.append(value)
    if values:
        candidate, count = Counter(values).most_common(1)[0]
        if count >= 2 and len(set(values)) == 1:
            return candidate
    return base
