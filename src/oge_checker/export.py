
import argparse
import json
from pathlib import Path

from .corrections import apply_corrections
from .evaluate import evaluate
from .recognize import relative, write_review
from .answers import effective_answer, field_value


def text_cell(sheet, row, column, value):
    cell = sheet.cell(row, column, value)
    if isinstance(value, str):

        cell.data_type = 's'
        cell.number_format = '@'
    return cell


def add_row(sheet, values):
    row = sheet.max_row + 1 if sheet.max_row > 1 or sheet.cell(1, 1).value is not None else 1
    for column, value in enumerate(values, 1):
        text_cell(sheet, row, column, value)


def workbook(data, metrics, destination):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    from .grading import grade_page
    book = Workbook()
    sheet = book.active
    sheet.title = 'Результаты'
    key = data.get('answer_key')
    numbers = sorted({int(n) for tasks in key['variants'].values() for n in tasks} if key else
                     {int(f['name'][7:]) for p in data['pages'] for f in p['fields'] if f['name'].startswith('answer_')})
    add_row(sheet, ['ФИО'] + numbers + ['Сумма баллов', 'Оценка'])
    statistics = {n: {'correct': 0, 'assigned': 0} for n in numbers}
    totals, marks = [], []
    for page in data['pages']:
        values = {f['name']: field_value(f) or '' for f in page['fields']}
        name = ' '.join(values.get(part, '') for part in ('surname', 'first_name', 'patronymic')).strip()
        score = grade_page(page, key) if key else {}
        task_results = {t['number']: t for t in score.get('tasks', [])}
        variant = page.get('variant') or (key or {}).get('default_variant')
        assigned = (key or {}).get('variants', {}).get(variant, {})
        for n in numbers:
            if str(n) in assigned:
                statistics[n]['assigned'] += 1
            task = task_results.get(n)
            if task and task['points'] is not None and task['points'] == task['maximum']:
                statistics[n]['correct'] += 1
        add_row(sheet, [name] + [task_results.get(n, {}).get('points') for n in numbers] +
                [score.get('total'), score.get('grade')])
        if score.get('total') is not None:
            totals.append(score['total'])
        if score.get('grade') is not None:
            marks.append(score['grade'])
    student_end = sheet.max_row
    sheet.append([])
    add_row(sheet, ['Решили полностью, чел.'] + [statistics[n]['correct'] for n in numbers])
    add_row(sheet, ['Решили полностью, %'] +
            [statistics[n]['correct']/statistics[n]['assigned'] if statistics[n]['assigned'] else None for n in numbers])
    for cell in list(sheet.rows)[-1][1:len(numbers)+1]:
        cell.number_format = '0.00%'
    sheet.append([])
    add_row(sheet, ['Сводка', 'Значение'])
    for grade in (2, 3, 4, 5):
        add_row(sheet, [f'Оценка {grade}', marks.count(grade)])
    add_row(sheet, ['Средний балл за работу', sum(totals)/len(totals) if totals else None])
    sheet.cell(sheet.max_row, 2).number_format = '0.00'
    add_row(sheet, ['Средняя оценка', sum(marks)/len(marks) if marks else None])
    sheet.cell(sheet.max_row, 2).number_format = '0.00'
    sheet.freeze_panes = 'B2'
    sheet.auto_filter.ref = f'A1:{get_column_letter(len(numbers)+3)}{student_end}'
    for cell in sheet[1]:
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', fgColor='713DC5')
    for row in sheet:
        for cell in row:
            cell.alignment = Alignment(vertical='center', wrap_text=True, horizontal='left' if cell.column == 1 else 'center')
    sheet.column_dimensions['A'].width = 38
    for col in range(2, len(numbers)+2):
        sheet.column_dimensions[get_column_letter(col)].width = 9
    for col in (len(numbers)+2, len(numbers)+3):
        sheet.column_dimensions[get_column_letter(col)].width = 18
    book.save(destination)


def export(recognition_path, corrections_path, output):
    recognition_path, corrections_path, output = (path.resolve() for path in
                                                  (recognition_path, corrections_path, output))
    recognition = json.loads(recognition_path.read_text(encoding='utf-8'))
    corrections = json.loads(corrections_path.read_text(encoding='utf-8'))
    if recognition.get('run_status') != 'complete':
        raise ValueError('Сначала завершите запуск OCR')
    data = apply_corrections(recognition, corrections)
    metrics = evaluate(recognition, corrections)
    if output.exists() and any(output.iterdir()):
        raise ValueError('Папка экспорта должна быть пустой; укажите новую --output')
    output.mkdir(parents=True, exist_ok=True)

    for page in data['pages']:
        for key in ('original', 'replacements'):
            if key in page:
                page[key] = relative(recognition_path.parent / page[key], output)
        for field in page['fields']:
            for key in ('original', 'cleaned'):
                field[key] = relative(recognition_path.parent / field[key], output)
    data['corrections_source'] = str(corrections_path)
    workbook(data, metrics, output / 'students.xlsx')
    (output / 'confirmed.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'metrics.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8')
    write_review(output, data)
    print(f'Подтверждено полей: {metrics["reviewed_fields"]}; таблица: {output / "students.xlsx"}')
    return data, metrics


def main():
    parser = argparse.ArgumentParser(description='Экспорт ручных правок в Excel и JSON')
    parser.add_argument('recognition', type=Path)
    parser.add_argument('corrections', type=Path)
    parser.add_argument('--output', type=Path, default=Path('output/results'))
    args = parser.parse_args()
    try:
        export(args.recognition, args.corrections, args.output)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f'Ошибка: {exc}\n')


if __name__ == '__main__':
    main()
