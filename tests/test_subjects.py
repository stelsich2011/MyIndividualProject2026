from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from openpyxl import load_workbook

from oge_checker.answer_formats import constrained_read, format_error
from oge_checker.grading import grade_page, task_points, validate_key
from oge_checker.keys import key_from_rows
from oge_checker.session import Session
from oge_checker.image_io import write_image
from oge_checker.recognize import recognize
from oge_checker.subjects import catalog, school_grade, subject
from test_grading import complete_data


def subject_key(identifier='math', count=None):
    profile = subject(identifier)
    tasks = list(profile['tasks'].items())
    if count:
        tasks = tasks[:count]
    return dict(schema_version=1, demo=False, subject=identifier, default_variant='1', variants={
        '1': {n: dict(t, accepted=['7']) for n, t in tasks}})


class SubjectTests(unittest.TestCase):
    def test_registry_profiles_and_formats(self):
        for identifier in catalog()['subjects']:
            profile = subject(identifier)
            key = subject_key(identifier)
            for task in key['variants']['1'].values():
                if task['format']['type'] == 'cyrillic':
                    task['accepted'] = ['СЛОВО']
            validate_key(key)
            self.assertLessEqual(sum(t['points'] for t in profile['tasks'].values()), profile['full_maximum'])
        self.assertEqual(subject('math')['full_maximum'], 31)
        self.assertEqual(subject('russian')['full_maximum'], 37)
        self.assertNotIn('1', subject('russian')['tasks'])

    def test_short_keys_keep_complete_grade_thresholds_and_geometry(self):
        key = subject_key(count=10)
        validate_key(key)
        score = grade_page(complete_data()['pages'][0], key)
        self.assertEqual((score['total'], score['maximum'], len(score['tasks'])), (10, 10, 10))
        self.assertEqual(score['grade'], 2)
        page = complete_data()['pages'][0]
        key = subject_key()
        self.assertEqual(grade_page(page, key)['grade'], 4)
        for field in page['fields'][14:]:
            field['corrected_text'] = ''
        self.assertEqual(grade_page(page, key)['grade'], 2)

    def test_full_grade_thresholds_and_russian_literacy(self):
        for identifier in catalog()['subjects']:
            profile = subject(identifier)
            key = subject_key(identifier)
            for mark, threshold in profile['grade_thresholds'].items():
                score = dict(total=threshold, tasks=[dict(number=15, points=2)])
                self.assertEqual(school_grade(score, key, dict(literacy_points=12)), int(mark))
        key = subject_key('russian')
        score = dict(total=33, tasks=[])
        self.assertIsNone(school_grade(score, key))
        for literacy, expected in [(9, 5), (8, 4), (5, 3)]:
            self.assertEqual(school_grade(score, key, dict(literacy_points=literacy)), expected)
        self.assertIsNone(school_grade(dict(total=None), key))

    def test_partial_credit_and_order_rules(self):
        task = dict(accepted=['123'], points=2, format=dict(type='digits'), scoring='positional')
        for value, points in [('123', 2), ('124', 1), ('321', 0), ('12', 0), ('12А', 0)]:
            self.assertEqual(task_points(value, task), points)
        task['scoring'] = 'set'
        for value, points in [('321', 2), ('12', 1), ('124', 1), ('1234', 0), ('1', 0)]:
            self.assertEqual(task_points(value, task), points)
        task.update(scoring='unordered', points=1)
        self.assertEqual(task_points('231', task), 1)
        self.assertEqual(task_points('124', task), 0)

    def test_validation_preserves_leading_zero_and_detects_bad_key(self):
        rows = [['Вариант', 'Задание', 'Ответ', 'Баллы'], ['02', '1', '007', '2']]
        key = key_from_rows(rows)
        task = key['variants']['02']['1']
        task['format'] = dict(type='digits', min_length=3, max_length=3)
        validate_key(key)
        self.assertEqual(task_points('007', task), 2)
        self.assertTrue(format_error('7', task['format']))
        self.assertTrue(format_error('А07', task['format']))
        self.assertFalse(format_error('', task['format']))
        task['accepted'] = ['А07']
        with self.assertRaises(ValueError):
            validate_key(key)

    def test_format_rereading_requires_consensus_and_keeps_empty_answers(self):
        image = np.full((40, 100), 255, np.uint8)
        spec = dict(type='digits', min_length=3, max_length=3)
        def read(values):
            source = iter(values)
            return lambda _: (next(source), .9)
        self.assertEqual(constrained_read('О07', image, spec, read(['007', '007', 'О07'])), '007')
        self.assertEqual(constrained_read('О07', image, spec, read(['007', '017', '007'])), 'О07')
        self.assertEqual(constrained_read('', image, spec, read([])), '')
        self.assertEqual(constrained_read('007', image, spec, read([])), '007')

    def test_ocr_uses_zero_padded_field_format_without_guessing_from_key(self):
        image = np.full((40, 100, 3), 255, np.uint8)
        key = subject_key(count=1)
        key['variants']['1']['1'].update(accepted=['999'], format=dict(type='digits', min_length=3, max_length=3))
        class Engine:
            def __init__(self):
                self.readings = iter(['O07', '007', '007', 'O07'])
            def read(self, image):
                return next(self.readings), .9
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            write_image(folder / 'scan.png', image)
            manifest = dict(template='oge_math_form1_v1', pages=[dict(page=1, status='prepared', original='scan.png',
                fields=dict(replacements=dict(image='scan.png'), answer_01=dict(image='scan.png')))])
            (folder / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            updates = []
            with patch('oge_checker.recognize.preprocess', return_value=(image, False)), \
                    patch('oge_checker.recognize.recognize_replacements', return_value=({}, [], [])), \
                    patch('oge_checker.text_answers.refine_text', return_value=('O07', [])):
                result = recognize(folder, folder / 'out', engine=Engine(), restore_decimals=False,
                                   answer_key=key, progress=lambda current, total: updates.append((current, total)))
            field = result['pages'][0]['fields'][0]
            self.assertEqual(field['raw_text'], 'O07')
            self.assertEqual(field['candidate'], '007')
            self.assertIsNone(field['corrected_text'])
            self.assertFalse(field['reviewed'])
            self.assertEqual(result['answer_key'], key)
            self.assertEqual(updates, [(1, 1)])

    def test_excel_points_statistics_variants_and_missing_pages(self):
        data = complete_data()
        first = data['pages'][0]
        first['fields'].insert(0, dict(id='1:surname', name='surname', candidate='=ИВАНОВ', corrected_text=None))
        second = deepcopy(first)
        second.update(page=2, variant='2')
        for field in second['fields']:
            field['id'] = field['id'].replace('1:', '2:')
        third = dict(page=3, status='needs_review', fields=[], error='Нет меток')
        data['pages'] += [second, third]
        key = subject_key('informatics', 2)
        key['variants']['1']['1'].update(points=2, scoring='positional', accepted=['78'])
        first['fields'][1]['corrected_text'] = '79'
        key['variants']['2'] = {'1': dict(accepted=['7'], points=2)}
        second['fields'][1]['corrected_text'] = '7'
        session = Session(data, Path('.'))
        session.set_key(key)
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / 'Отчёт.xlsx'
            session.export_excel(destination)
            book = load_workbook(destination)
            self.assertEqual(book.sheetnames, ['Результаты'])
            sheet = book.active
            self.assertEqual([c.value for c in sheet[1]], ['ФИО', 1, 2, 'Сумма баллов', 'Оценка'])
            self.assertEqual(sheet['A2'].value, '=ИВАНОВ')
            self.assertEqual(sheet['A2'].data_type, 's')
            self.assertEqual([sheet.cell(2, c).value for c in range(2, 6)], [1, 1, 2, 2])
            self.assertEqual([sheet.cell(3, c).value for c in range(2, 6)], [2, None, 2, 2])
            self.assertIsNone(sheet['D4'].value)
            rows = {row[0].value: row for row in sheet if row[0].value}
            counts = rows['Решили полностью, чел.']
            self.assertEqual([counts[1].value, counts[2].value], [1, 1])
            percentages = rows['Решили полностью, %']
            self.assertAlmostEqual(percentages[1].value, 1/3)
            self.assertAlmostEqual(percentages[2].value, .5)
            self.assertEqual(percentages[1].number_format, '0.00%')
            self.assertEqual(rows['Оценка 2'][1].value, 2)
            self.assertEqual(rows['Средний балл за работу'][1].value, 2)
            self.assertEqual(sheet.freeze_panes, 'B2')
            self.assertEqual(sheet.auto_filter.ref, 'A1:E4')
