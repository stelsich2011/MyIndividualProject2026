
from copy import deepcopy
import random

from .recognize import normalize
from .answers import effective_answer


def demo_key(seed=42):
    generator = random.Random(seed)
    return {'schema_version': 1, 'demo': True, 'title': 'ДЕМО: случайные цифры, не ключи ОГЭ',
            'seed': seed, 'default_variant': 'demo', 'variants': {'demo': {
                str(number): {'accepted': [str(generator.randrange(10))], 'points': 1}
                for number in range(1, 20)}}}


def validate_key(key):
    if key.get('schema_version') != 1 or not isinstance(key.get('demo'), bool):
        raise ValueError('Ключ должен содержать schema_version: 1 и demo: true/false')
    variants = key.get('variants')
    if not isinstance(variants, dict) or not variants:
        raise ValueError('В ключе отсутствуют варианты')
    for variant, tasks in variants.items():
        if not isinstance(variant, str) or not variant.strip() or not isinstance(tasks, dict) or not tasks or any(not isinstance(n, str) or not n.isdecimal() or str(int(n)) != n or not 1 <= int(n) <= 19 for n in tasks):
            raise ValueError('Вариант должен содержать выбранные задания с номерами 1–19')
        for task in tasks.values():
            if not isinstance(task, dict):
                raise ValueError('Неверный формат задания')
            accepted, points = task.get('accepted'), task.get('points')
            if not isinstance(accepted, list) or not accepted or any(not isinstance(x, str) or not normalize(x) for x in accepted):
                raise ValueError('accepted должен содержать непустые строковые ответы')
            if type(points) is not int or not 1 <= points <= 100:
                raise ValueError('points должен быть целым числом от 1 до 100')
            from .answer_formats import validate_format, format_error
            validate_format(task.get('format', {}))
            for value in accepted:
                issue = format_error(value, task.get('format'))
                if issue:
                    raise ValueError(issue)
            if task.get('scoring', 'exact') not in ('exact', 'positional', 'unordered', 'set'):
                raise ValueError('Неизвестное правило начисления баллов')
    if key.get('subject'):
        from .subjects import subject
        subject(key['subject'])
    if key.get('default_variant') is not None and key['default_variant'] not in variants:
        raise ValueError('default_variant отсутствует в variants')
    return key


def parse_replacements(text):
    result = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        task, separator, answer = line.partition('=')
        task = task.strip()
        if not separator or not task.isdecimal() or not 1 <= int(task) <= 19:
            raise ValueError('Каждая замена задаётся строкой номер=ответ, например 12=3')
        task = str(int(task))
        if task in result:
            raise ValueError(f'Повторная замена задания {task}: выберите окончательный ответ')
        result[task] = answer.strip()
    return result


def grade_page(page, key):
    variant = page.get('variant') or key.get('default_variant')
    base = {'demo': key['demo'], 'variant': variant, 'total': None, 'provisional': None,
            'maximum': None, 'tasks': [], 'status': 'Не определён вариант'}
    if page.get('status') != 'prepared':
        base.update(status='Не обработан бланк',warnings=[page.get('error','Не удалось выделить поля на скане')])
        return base
    if variant not in key['variants']:
        return base
    tasks = key['variants'][variant]
    changes = page.get('replacement_answers', {})
    if not isinstance(changes, dict) or any(not str(k).isdecimal() or not 1 <= int(k) <= 19 or not isinstance(v, str) for k, v in changes.items()):
        raise ValueError(f'Неверный блок замен страницы {page["page"]}')
    earned, ready = 0, 0
    alerts = list(page.get('replacement_warnings', []))
    if page.get('replacements') and 'automatic_replacements' not in page and not page.get('replacements_reviewed'):
        alerts.append('Старый проект: блок замен автоматически не распознавался')
    if page.get('replacement_draft_error'):
        alerts.append(page['replacement_draft_error'])
    for number, task in sorted(tasks.items(), key=lambda item: int(item[0])):
        value, source, issues = effective_answer(page, number)
        confirmed = isinstance(value, str)
        alerts.extend(f'Задание {number}: {issue}' for issue in issues)
        points = None
        status = 'Ошибка обработки'
        if confirmed:
            ready += 1
            points = task_points(value, task)
            match = points == task['points']
            from .answer_formats import format_error
            issue = format_error(value, task.get('format'))
            if issue:
                issues.append(issue)
                alerts.append(f'Задание {number}: {issue}')
            earned += points
            status = 'Верно' if match else ('Частично верно' if points else ('Нет ответа' if not normalize(value) else 'Неверно'))
        base['tasks'].append({'number': int(number), 'answer': value, 'source': source,
                              'accepted': task['accepted'], 'points': points,
                              'maximum': task['points'], 'status': status, 'warnings': issues})
    base['maximum'] = sum(task['points'] for task in tasks.values())

    base['provisional'] = earned if ready else None
    if page.get('status') != 'prepared':
        base['status'] = 'Нужна проверка подготовки скана'
    elif ready != len(tasks):
        base['status'] = f'Обработано ответов {ready}/{len(tasks)}'
    else:
        base['total'] = earned
        base['status'] = 'Автоматически: есть сомнения' if alerts else 'Проверено автоматически'
    base['warnings'] = alerts
    from .subjects import school_grade
    base['grade'] = school_grade(base, key, page)
    if key['demo']:
        base['status'] = 'ДЕМО — ' + base['status']
    return base


def task_points(value, task):
    from collections import Counter
    from .answer_formats import format_error
    value = normalize(value)
    if not value or format_error(value, task.get('format')):
        return 0
    result = 0
    for answer in task['accepted']:
        answer = normalize(answer)
        rule = task.get('scoring', 'exact')
        if value == answer or rule in ('unordered', 'set') and Counter(value) == Counter(answer):
            return task['points']
        partial = False
        if rule == 'positional' and len(value) == len(answer):
            partial = sum(a != b for a, b in zip(value, answer)) == 1
        if rule == 'set' and len(value) <= len(answer):
            partial = max(sum((Counter(value)-Counter(answer)).values()), sum((Counter(answer)-Counter(value)).values())) == 1
        if partial:
            result = max(result, min(1, task['points']-1))
    return result


def grade_data(data, key):
    validate_key(key)
    result = deepcopy(data)
    result['answer_key'] = deepcopy(key)
    for page in result['pages']:
        page['grading'] = grade_page(page, key)
    return result
