from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path


@lru_cache(maxsize=1)
def catalog():
    return json.loads(Path(__file__).with_name('config').joinpath('subjects.json').read_text(encoding='utf-8'))


def subject(identifier):
    if identifier not in catalog()['subjects']:
        raise ValueError('Неизвестный предмет')
    return deepcopy(catalog()['subjects'][identifier])


def task_defaults(identifier, number):
    profile = subject(identifier)
    return deepcopy(profile['tasks'].get(str(number), {'points': 1, 'format': {'type': 'mixed'}, 'scoring': 'exact'}))


def school_grade(score, key, page=None):
    if score.get('total') is None or not key.get('subject'):
        return None
    profile = subject(key['subject'])
    total = score['total']
    if total > profile['full_maximum']:
        return None
    grade = 2
    for mark, threshold in profile['grade_thresholds'].items():
        if total >= threshold:
            grade = int(mark)
    if profile.get('geometry_tasks') and grade >= 3:
        geometry = sum(t['points'] or 0 for t in score['tasks'] if t['number'] in profile['geometry_tasks'])
        if geometry < 2:
            return 2
    if profile.get('literacy_required') and grade >= 4:
        literacy = (page or {}).get('literacy_points')
        if literacy is None:
            return None
        if grade == 5 and literacy < 9:
            grade = 4
        if grade == 4 and literacy < 6:
            grade = 3
    return grade
