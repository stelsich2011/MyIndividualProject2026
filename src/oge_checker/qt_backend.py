from datetime import datetime
from functools import wraps
from copy import deepcopy
import csv
import json
from pathlib import Path

from PySide6.QtCore import QObject, Property, QSettings, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QMessageBox

from .answers import field_value, warnings
from .grading import grade_page, parse_replacements
from .keys import HEADERS, key_from_rows, load_key, write_template
from .session import Session
from .answer_formats import TYPES, format_error
from .subjects import catalog, subject


class OperationWorker(QThread):
    completed = Signal(str, object)
    failed = Signal(str)

    def __init__(self, kind, operation, parent=None):
        super().__init__(parent)
        self.kind, self.operation = kind, operation

    def run(self):
        try:
            self.completed.emit(self.kind, self.operation())
        except Exception as exc:
            self.failed.emit(str(exc))


def guarded(method):
    @wraps(method)
    def call(self, *args):
        try:
            if self._busy:
                return False
            return method(self, *args)
        except Exception as exc:
            self.error.emit(str(exc))
            return False
    return call


class PdfWorker(QThread):
    completed = Signal(str)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, pdf, folder, pages, parent=None, key=None):
        super().__init__(parent)
        self.pdf, self.folder, self.pages = Path(pdf), Path(folder), pages
        self.key = deepcopy(key)

    def run(self):
        try:
            from .pipeline import prepare
            from .recognize import recognize
            self.progress.emit('Подготовка сканов…')
            prepare(self.pdf, self.folder / 'prepared', self.pages)
            self.progress.emit('Распознавание ответов…')
            recognize(self.folder / 'prepared', self.folder / 'ocr', answer_key=self.key,
                      progress=lambda current, total: self.progress.emit(f'Распознавание: {current}/{total}'))
            session = Session.open(self.folder / 'ocr/recognition.json')
            if self.key:
                session.set_key(self.key)
            session.save(self.folder / 'project.json')
            self.completed.emit(str(self.folder / 'project.json'))
        except Exception as exc:
            self.failed.emit(str(exc))


class Backend(QObject):
    changed = Signal()
    error = Signal(str)
    pdfChosen = Signal(str)
    themeChanged = Signal()

    def __init__(self, settings=None):
        super().__init__()
        self.settings = settings if settings is not None else QSettings('OGEChecker', 'OGEChecker')
        self._dark_theme = self.settings.value('appearance/darkTheme', True, type=bool)
        self.session = None
        self.pending_key = None
        self.project_path = None
        self.page_number = None
        self.field_id = ''
        self._busy = False
        self._status = 'Загрузите PDF или откройте проект'
        self._state = {}
        self.worker = None
        self.key_rows = []
        self.key_demo = False
        self.key_subject = 'math'
        self.key_variant = ''
        self._hidden_key_rows = {}
        self.refresh()

    state = Property('QVariantMap', lambda self: self._state, notify=changed)
    busy = Property(bool, lambda self: self._busy, notify=changed)
    status = Property(str, lambda self: self._status, notify=changed)
    keyRows = Property('QVariantList', lambda self: self.key_rows, notify=changed)
    darkTheme = Property(bool, lambda self: self._dark_theme, notify=themeChanged)
    subjects = Property('QVariantList', lambda self: [dict(id=k, name=v['name']) for k, v in catalog()['subjects'].items()], constant=True)
    answerTypes = Property('QVariantList', lambda self: [dict(id=k, name=v) for k, v in TYPES.items()], constant=True)
    keySubject = Property(str, lambda self: self.key_subject, notify=changed)
    keyVariant = Property(str, lambda self: self.key_variant, notify=changed)
    keyVariants = Property('QStringList', lambda self: list(dict.fromkeys(r['variant'] for r in self.key_rows)), notify=changed)
    keyVisibleRows = Property('QVariantList', lambda self: [dict(r, rowIndex=i) for i, r in enumerate(self.key_rows) if r['variant'] == self.key_variant], notify=changed)
    keySummary = Property('QVariantMap', lambda self: self.key_summary(), notify=changed)

    def key_summary(self):
        profile = subject(self.key_subject)
        rows = [r for r in self.key_rows if r['variant'] == self.key_variant]
        return dict(count=len(rows), maximum=sum(int(r['points']) for r in rows if str(r['points']).isdigit()),
                    limit=len(profile['tasks']), fullMaximum=profile['full_maximum'],
                    scale='; '.join(f'{grade}: от {points}' for grade, points in profile['grade_thresholds'].items()),
                    note='Шкала полного ОГЭ-2026; пороги не уменьшаются для сокращённой работы. Геометрия ≥2 баллов для математики; для русского учитывается грамотность.')

    def format_for(self, name, page=None):
        page = page or self.page() or {}
        key = (self.session.key if self.session else self.pending_key) or {}
        tasks = key.get('variants', {}).get(page.get('variant') or key.get('default_variant'), {})
        return tasks.get(str(int(name[7:])), {}).get('format', {}) if name.startswith('answer_') else {}

    @Slot(bool)
    def setDarkTheme(self, dark):
        if self._dark_theme != dark:
            self._dark_theme = dark
            self.settings.setValue('appearance/darkTheme', dark)
            self.settings.sync()
            self.themeChanged.emit()

    def page(self):
        return next((p for p in self.session.data['pages'] if p['page'] == self.page_number), None) if self.session else None

    def field(self):
        return next((f for f in (self.page() or {}).get('fields', []) if f['id'] == self.field_id), None)

    def image_url(self, value):
        path = self.session.root / value if self.session and value else None
        return QUrl.fromLocalFile(str(path.resolve())).toString() if path and path.is_file() else ''

    def refresh(self):
        pages, fields, results = [], [], []
        for p in self.session.data['pages'] if self.session else []:
            names = {f['name']: field_value(f) or '' for f in p['fields']}
            name = ' '.join(names.get(n, '') for n in ('surname', 'first_name')).strip() or 'Не распознано'
            pages.append({'number': p['page'], 'name': name, 'prepared': p['status'] == 'prepared'})
            score = grade_page(p, self.session.key) if self.session.key else {}
            results.append({'page': p['page'], 'name': name, 'total': str(score.get('total')) if score.get('total') is not None else '—',
                            'grade': str(score.get('grade')) if score.get('grade') is not None else '—',
                            'status': score.get('status', p.get('error', 'Загрузите ключи'))})
        page = self.page() or {}
        for f in page.get('fields', []):
            issue = format_error(field_value(f) or '', self.format_for(f['name'], page))
            fields.append({'id': f['id'], 'label': f['label'], 'candidate': f.get('candidate', ''), 'value': field_value(f) or '',
                           'confidence': f"{f['confidence']:.0%}" if f.get('confidence') is not None else '—',
                           'suspect': bool(warnings(f) or issue), 'warning': '; '.join(warnings(f) + ([issue] if issue else []))})
        if self.field_id not in [f['id'] for f in fields]:
            self.field_id = fields[0]['id'] if fields else ''
        selected = next((f for f in fields if f['id'] == self.field_id), {})
        raw_field = self.field() or {}
        key = (self.session.key if self.session else self.pending_key) or {}
        metrics = self.session.metrics() if self.session else None
        self._state = {'pages': pages, 'fields': fields, 'results': results, 'selected': selected,
                       'pageNumber': self.page_number or 0, 'image': self.image_url(raw_field.get('original')),
                       'keyTitle': key.get('title', 'Ключи не загружены'), 'demo': key.get('demo', False),
                       'variants': list(key.get('variants', {})), 'variant': page.get('variant') or key.get('default_variant') or '',
                       'draft': page.get('replacement_draft', '\n'.join(f'{n}={v}' for n, v in page.get('replacement_answers', {}).items())),
                       'pageError': page.get('error', ''), 'replacementWarnings': '\n'.join(page.get('replacement_warnings', [])),
                       'metrics': json.dumps(metrics, ensure_ascii=False, indent=2) if metrics and metrics['reviewed_fields'] else 'Точность не измерена. Загрузите эталонную расшифровку.',
                       'dirty': bool(self.session and self.session.dirty), 'hasProject': self.session is not None,
                       'subjectName': subject(key['subject'])['name'] if key.get('subject') else 'Предмет не задан',
                       'subject': key.get('subject', ''),
                       'literacy': page.get('literacy_points', -1),
                       'summary': f"Обработано бланков: {sum(p['prepared'] for p in pages)}/{len(pages)}" if pages else 'Нет открытого проекта'}
        self.changed.emit()

    @Slot(result=bool)
    def canLeave(self):
        if self._busy:
            self.error.emit('Дождитесь завершения текущей операции')
            return False
        if self.session and self.session.dirty:
            answer = QMessageBox.question(None, 'Сохранить проект?', 'Есть несохранённые изменения.',
                                          QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
            if answer == QMessageBox.Cancel:
                return False
            if answer == QMessageBox.Save:
                self._saving_before_leave = True
                try:
                    return self.saveProject()
                finally:
                    self._saving_before_leave = False
        return True

    @Slot(str, result=bool)
    @guarded
    def openPath(self, path):
        session = Session.open(path)
        if self.pending_key and not session.key:
            session.set_key(self.pending_key)
        self.session, self.project_path = session, Path(path)
        self.page_number = session.data['pages'][0]['page'] if session.data['pages'] else None
        self.field_id = ''
        self._status = f'Открыто: {Path(path).name}'
        self.refresh()
        return True

    @Slot()
    @guarded
    def openProject(self):
        if self.canLeave():
            path, _ = QFileDialog.getOpenFileName(None, 'Открыть проект', '', 'Проект (*.json)')
            if path:
                self.run_operation('open', 'Загрузка проекта…', lambda: (Session.open(path), Path(path)))

    @Slot(result=bool)
    @guarded
    def saveProject(self):
        if not self.session:
            raise ValueError('Сначала откройте проект')
        path, _ = QFileDialog.getSaveFileName(None, 'Сохранить проект', str(self.project_path or 'project.json'), 'JSON (*.json)')
        if not path:
            return False
        if getattr(self, '_saving_before_leave', False):
            self.session.save(path)
            self.session.dirty = False
            self.project_path = Path(path)
            self.refresh()
            return True
        snapshot = Session(self.session.snapshot(), self.session.root)
        self.run_operation('save', 'Сохранение проекта…', lambda: (snapshot.save(path), path)[1])
        return True

    @Slot()
    @guarded
    def exportExcel(self):
        if not self.session:
            raise ValueError('Сначала откройте проект')
        path, _ = QFileDialog.getSaveFileName(None, 'Экспорт Excel', 'results.xlsx', 'Excel (*.xlsx)')
        if path:
            snapshot = Session(self.session.snapshot(), self.session.root)
            self.run_operation('export', 'Формирование Excel и статистики…', lambda: (snapshot.export_excel(path), path)[1])

    @Slot(int)
    def selectPage(self, number):
        if self._busy:
            return
        self.page_number = number
        self.field_id = ''
        self.refresh()

    @Slot(str)
    def selectField(self, identifier):
        if self._busy:
            return
        self.field_id = identifier
        self.refresh()

    @Slot(str)
    @guarded
    def editField(self, text):
        field = self.field()
        if field is not None:
            field['corrected_text'] = text
            self.session.dirty = True
            self.refresh()

    @Slot()
    @guarded
    def nextField(self):
        fields = (self.page() or {}).get('fields', [])
        for i, f in enumerate(fields):
            if f['id'] == self.field_id and i + 1 < len(fields):
                self.field_id = fields[i + 1]['id']
                break
        self.refresh()

    @Slot(str, bool)
    @guarded
    def setVariant(self, variant, all_pages):
        if not self.session or not self.session.key or variant not in self.session.key['variants']:
            return
        for p in self.session.data['pages'] if all_pages else [self.page()]:
            if p is not None:
                p['variant'] = variant
        self.session.dirty = True
        self.refresh()

    @Slot(str)
    def setDraft(self, text):
        if self.page() is not None and not self._busy:
            self.page()['replacement_draft'] = text
            self.session.dirty = True
            self._state.update(draft=text, dirty=True)
            self.changed.emit()

    @Slot(str)
    @guarded
    def applyReplacements(self, text):
        if self.page() is not None:
            changes = parse_replacements(text)
            self.page().update(replacement_draft=text, replacement_answers=changes)
            self.session.dirty = True
            self.refresh()

    @Slot(str)
    def showImage(self, kind):
        if self.page():
            url = self.image_url(self.page().get('replacements' if kind == 'replacements' else 'original'))
            if url:
                QDesktopServices.openUrl(QUrl(url))
            else:
                self.error.emit('Изображение не найдено')

    @Slot(str)
    @guarded
    def importFile(self, kind):
        path, _ = QFileDialog.getOpenFileName(None, 'Выберите файл', '', 'Данные (*.json *.xlsx *.csv)')
        if not path:
            return
        if kind == 'keys':
            self.run_operation('keys', 'Загрузка ключей…', lambda: load_key(path))
            return
        elif self.session:
            snapshot = Session(self.session.snapshot(), self.session.root)
            def operation():
                if kind == 'reference':
                    snapshot.load_reference(path)
                else:
                    snapshot.load_corrections(path)
                return snapshot
            self.run_operation('import', 'Загрузка эталона и правок…', operation)
            return
        else:
            raise ValueError('Сначала откройте проект')
        self.refresh()

    @Slot(str)
    @guarded
    def saveTemplate(self, kind):
        path, _ = QFileDialog.getSaveFileName(None, 'Сохранить', 'keys.xlsx' if kind == 'keys' else 'reference.csv', 'Таблица (*.xlsx *.csv)' if kind == 'keys' else 'CSV (*.csv)')
        if not path:
            return
        if kind == 'keys':
            write_template(path)
        else:
            if not self.session:
                raise ValueError('Сначала откройте проект')
            with Path(path).open('w', encoding='utf-8-sig', newline='') as stream:
                writer = csv.writer(stream, delimiter=';')
                writer.writerow(['source_id', 'страница', 'поле', 'текст'])
                writer.writerows([self.session.data['source_id'], p['page'], f['name'], ''] for p in self.session.data['pages'] for f in p['fields'])

    @Slot()
    @guarded
    def saveMetrics(self):
        if not self.session:
            raise ValueError('Сначала откройте проект')
        path, _ = QFileDialog.getSaveFileName(None, 'Отчёт точности', 'accuracy.json', 'JSON (*.json)')
        if path:
            snapshot = Session(self.session.snapshot(), self.session.root)
            self.run_operation('metrics', 'Формирование отчёта точности…',
                               lambda: Path(path).write_text(json.dumps(snapshot.metrics(), ensure_ascii=False, indent=2), encoding='utf-8'))

    @Slot()
    def beginKeys(self):
        key = (self.session.key if self.session else self.pending_key)
        self.key_demo = (key or {}).get('demo', False)
        self.key_subject = (key or {}).get('subject', 'math')
        self._hidden_key_rows = {}
        self.key_rows = []
        if key:
            for variant, tasks in key['variants'].items():
                for number, task in sorted(tasks.items(), key=lambda item: int(item[0])):
                    self.key_rows.append(dict(variant=variant, number=number, answer='|'.join(task['accepted']), points=str(task['points']),
                        type=task.get('format', {}).get('type', 'mixed'), minLength=task.get('format', {}).get('min_length', 0),
                        maxLength=task.get('format', {}).get('max_length', 0), scoring=task.get('scoring', 'exact')))
        else:
            self.key_rows = self.default_rows('1')
        self.key_variant = self.key_rows[0]['variant'] if self.key_rows else ''
        self.changed.emit()

    def default_rows(self, variant):
        return [dict(variant=variant, number=n, answer='', points=str(t['points']), type=t['format']['type'],
                     minLength=0, maxLength=0, scoring=t.get('scoring', 'exact')) for n, t in subject(self.key_subject)['tasks'].items()]

    @Slot(str)
    @guarded
    def selectKeySubject(self, identifier):
        subject(identifier)
        answers = {(r['variant'], r['number']): r['answer'] for r in self.key_rows}
        previous = {r['variant']: True for r in self.key_rows} or {'1': True}
        self.key_subject = identifier
        self.key_rows = [r for v in previous for r in self.default_rows(v)]
        for row in self.key_rows:
            row['answer'] = answers.get((row['variant'], row['number']), '')
        self._hidden_key_rows = {}
        self.key_variant = next(iter(previous))
        self.key_demo = False
        self.changed.emit()

    @Slot(str)
    def selectKeyVariant(self, variant):
        if variant in [r['variant'] for r in self.key_rows]:
            self.key_variant = variant
            self.changed.emit()

    @Slot(int)
    @guarded
    def setTaskCount(self, count):
        defaults = self.default_rows(self.key_variant)
        if not 1 <= count <= len(defaults):
            raise ValueError('Недопустимое количество кратких заданий')
        existing = self._hidden_key_rows.setdefault(self.key_variant, {})
        existing.update({r['number']: r for r in self.key_rows if r['variant'] == self.key_variant})
        self.key_rows = [r for r in self.key_rows if r['variant'] != self.key_variant] + [existing.get(r['number'], r) for r in defaults[:count]]
        self.changed.emit()

    @Slot(int, str, str)
    def editKeyCell(self, index, column, value):
        if 0 <= index < len(self.key_rows) and column in ('answer', 'points', 'type', 'minLength', 'maxLength'):
            self.key_rows[index][column] = int(value or 0) if column in ('minLength', 'maxLength') else value

    @Slot()
    def refreshKeys(self):
        self.changed.emit()

    @Slot(str)
    def addVariant(self, variant):
        variant = variant.strip()
        if variant and not any(r['variant'] == variant for r in self.key_rows):
            self.key_rows += self.default_rows(variant)
            self.key_variant = variant
            self.changed.emit()

    @Slot(str)
    def removeVariant(self, variant):
        if len(self.keyVariants) <= 1:
            return
        self.key_rows = [r for r in self.key_rows if r['variant'] != variant]
        self._hidden_key_rows.pop(variant, None)
        self.key_variant = self.key_rows[0]['variant'] if self.key_rows else ''
        self.changed.emit()

    @Slot(bool, result=bool)
    @guarded
    def applyKeys(self, save):
        rows = [list(HEADERS)] + [[r['variant'], r['number'], r['answer'], r['points']] for r in self.key_rows]
        key = key_from_rows(rows)
        key['demo'] = self.key_demo
        key['subject'] = self.key_subject
        key['scale_year'] = 2026
        for r in self.key_rows:
            key['variants'][r['variant']][r['number']].update(format=dict(type=r['type'], min_length=r['minLength'], max_length=r['maxLength']), scoring=r['scoring'])
        from .grading import validate_key
        validate_key(key)
        if save:
            path, _ = QFileDialog.getSaveFileName(None, 'Сохранить ключи', 'keys.json', 'JSON (*.json)')
            if not path:
                return False
            Path(path).write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding='utf-8')
        self.pending_key = key
        if self.session:
            self.session.set_key(key)
        self.refresh()
        return True

    @Slot(int)
    @guarded
    def setLiteracy(self, value):
        if self.page() is not None:
            if value < 0:
                self.page().pop('literacy_points', None)
            elif value <= 12:
                self.page()['literacy_points'] = value
            else:
                raise ValueError('Баллы грамотности: 0–12')
            self.session.dirty = True
            self.refresh()

    @Slot()
    @guarded
    def recheckOCR(self):
        if not self.session or not self.session.key:
            raise ValueError('Откройте проект и загрузите ключи')
        snapshot = Session(self.session.snapshot(), self.session.root)
        def operation():
            from .recognize import LocalOCR, preprocess, recognize_replacements
            from .image_io import read_image
            from .answer_formats import constrained_read, format_error
            engine = LocalOCR()
            for page in snapshot.data['pages']:
                tasks = snapshot.key['variants'].get(page.get('variant') or snapshot.key.get('default_variant'), {})
                for field in page['fields']:
                    if field.get('corrected_text') is not None or not field['name'].startswith('answer_'):
                        continue
                    spec = tasks.get(str(int(field['name'][7:])), {}).get('format')
                    if not spec or not format_error(field.get('candidate', ''), spec):
                        continue
                    cleaned, empty = preprocess(read_image(snapshot.root / field['original']))
                    if not empty:
                        before = field.get('candidate', '')
                        value = constrained_read(before, cleaned, spec, engine.read)
                        if before != value:
                            field.setdefault('adjustments', []).append(dict(rule='answer_format_consensus_v1', before=before, after=value))
                            field['candidate'] = value
                if page.get('replacements'):
                    image = read_image(snapshot.root / page['replacements'])
                    rows = (page.get('field_alignment') or {}).get('replacement_rows')
                    if rows != []:
                        page['automatic_replacements'], page['replacement_warnings'], page['replacement_entries'] = recognize_replacements(image, engine, rows)
            return snapshot
        self.run_operation('recheck', 'Уточнение OCR и автоматическая проверка замен…', operation)

    @Slot()
    @guarded
    def choosePdf(self):
        if self.canLeave():
            path, _ = QFileDialog.getOpenFileName(None, 'Загрузить сканы', '', 'PDF (*.pdf)')
            if path:
                self.pdfChosen.emit(path)

    @Slot(str, str)
    @guarded
    def startPdf(self, path, pages):
        from .__main__ import parse_pages
        numbers = parse_pages(pages) if pages.strip() else None
        folder = QFileDialog.getExistingDirectory(None, 'Папка для нового проекта')
        if folder:
            self.start_worker(Path(path), Path(folder) / datetime.now().strftime('oge_%Y%m%d_%H%M%S_%f'), numbers)

    def start_worker(self, pdf, folder, pages):
        if self._busy:
            return
        self._busy = True
        self._status = 'Подготовка сканов…'
        key = self.session.key if self.session else self.pending_key
        self.worker = PdfWorker(pdf, folder, pages, self, key=key)
        self.worker.progress.connect(self.worker_status)
        self.worker.completed.connect(self.worker_done)
        self.worker.failed.connect(self.worker_failed)
        self.worker.start()
        self.changed.emit()

    def run_operation(self, kind, status, operation):
        if self._busy:
            return False
        self._busy = True
        self._status = status
        self.worker = OperationWorker(kind, operation, self)
        self.worker.completed.connect(self.operation_done)
        self.worker.failed.connect(self.worker_failed)
        self.worker.start()
        self.changed.emit()
        return True

    @Slot(str, object)
    def operation_done(self, kind, result):
        self._busy = False
        if kind == 'save':
            self.project_path = Path(result)
            self.session.dirty = False
            self._status = 'Проект сохранён'
        elif kind == 'open':
            self.session, self.project_path = result
            if self.pending_key and not self.session.key:
                self.session.set_key(self.pending_key)
            self.page_number = self.session.data['pages'][0]['page'] if self.session.data['pages'] else None
            self.field_id = ''
            self._status = 'Проект открыт'
        elif kind == 'keys':
            self.pending_key = result
            if self.session:
                self.session.set_key(result)
            self._status = 'Ключи загружены'
        elif kind in ('recheck', 'import'):
            self.session = result
            self.session.dirty = True
            self._status = 'Распознавание уточнено; замены проверены автоматически' if kind == 'recheck' else 'Данные загружены'
        else:
            self._status = 'Готово'
        self.refresh()

    @Slot(str)
    def worker_status(self, text):
        self._status = text
        self.changed.emit()

    @Slot(str)
    def worker_done(self, path):
        self._busy = False
        self.openPath(path)

    @Slot(str)
    def worker_failed(self, text):
        self._busy = False
        self._status = 'Операция завершилась с ошибкой'
        self.changed.emit()
        self.error.emit(text)
