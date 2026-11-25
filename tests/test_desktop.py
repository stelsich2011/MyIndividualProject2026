import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from pathlib import Path
import tempfile
import time
from threading import Event
import unittest
from unittest.mock import patch

from PySide6.QtCore import QObject, QSettings
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication, QMessageBox
from oge_checker.qt_backend import Backend
from oge_checker.desktop import create_window
from oge_checker.session import Session
from test_grading import complete_data, all_sevens_key

QQuickStyle.setStyle('Basic')
app = QApplication.instance() or QApplication([])


class DesktopTests(unittest.TestCase):
    def wait_worker(self):
        deadline = time.monotonic() + 10
        while self.backend.busy and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.005)
        self.backend.worker.wait(10000)
        app.processEvents()
        self.assertFalse(self.backend.busy)
        self.assertFalse(self.errors)

    def setUp(self):
        settings_folder = tempfile.TemporaryDirectory()
        self.addCleanup(settings_folder.cleanup)
        self.backend = Backend(QSettings(str(Path(settings_folder.name) / 'settings.ini'), QSettings.IniFormat))
        self.backend.session = Session(complete_data(), Path('.'))
        self.backend.session.set_key(all_sevens_key())
        self.backend.page_number = 1
        self.backend.refresh()
        self.errors = []
        self.backend.error.connect(self.errors.append)

    def test_qml_window_and_controls_load(self):
        engine = create_window(app, self.backend)
        app.processEvents()
        root = engine.rootObjects()[0]
        self.assertEqual(root.objectName(), 'mainWindow')
        self.assertIsNotNone(root.findChild(QObject, 'answerEditor'))
        self.assertIsNotNone(root.findChild(QObject, 'pagesList'))
        self.assertIsNotNone(root.findChild(QObject, 'resultsList'))
        self.backend.session.dirty = False
        root.close()
        engine.deleteLater()
        app.processEvents()

    def test_edit_recalculates_and_next_field(self):
        self.backend.editField('8')
        self.assertEqual(self.backend.state['results'][0]['total'], '18')
        self.assertEqual(self.backend.session.data['pages'][0]['fields'][0]['corrected_text'], '8')
        self.backend.nextField()
        self.assertEqual(self.backend.field_id, '1:answer_02')

    def test_replacements_validate_before_application(self):
        self.backend.applyReplacements('1=8')
        self.assertEqual(self.backend.state['results'][0]['total'], '18')
        self.backend.applyReplacements('bad input')
        self.assertTrue(self.errors)
        self.assertEqual(self.backend.page()['replacement_answers'], {'1': '8'})

    def test_key_editor_round_trip_and_variants(self):
        self.backend.beginKeys()
        self.backend.editKeyCell(0, 'answer', '007|-0,5')
        self.assertTrue(self.backend.applyKeys(False))
        self.assertEqual(self.backend.session.key['variants']['demo']['1']['accepted'], ['007', '-0,5'])
        self.assertTrue(self.backend.session.key['demo'])
        self.backend.addVariant('2')
        self.assertEqual(len(self.backend.key_rows), 38)
        self.backend.removeVariant('2')
        self.assertEqual(len(self.backend.key_rows), 19)

    def test_save_cancel_and_close_cancel_preserve_dirty(self):
        with patch('oge_checker.qt_backend.QFileDialog.getSaveFileName', return_value=('', '')):
            self.assertFalse(self.backend.saveProject())
            self.assertTrue(self.backend.session.dirty)
        with patch('oge_checker.qt_backend.QMessageBox.question', return_value=QMessageBox.Cancel):
            self.assertFalse(self.backend.canLeave())

    def test_project_save_reopen_and_excel(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'project.json'
            self.backend.editField('007')
            with patch('oge_checker.qt_backend.QFileDialog.getSaveFileName', return_value=(str(path), '')):
                self.assertTrue(self.backend.saveProject())
            self.wait_worker()
            other = Backend()
            self.assertTrue(other.openPath(str(path)))
            self.assertEqual(other.state['selected']['value'], '007')
            other.session.export_excel(Path(temp) / 'results.xlsx')
            self.assertTrue((Path(temp) / 'results.xlsx').is_file())

    def test_subject_variants_count_and_format_validation(self):
        self.backend.beginKeys()
        self.backend.editKeyCell(0, 'answer', '007')
        self.backend.setTaskCount(10)
        self.backend.setTaskCount(11)
        self.assertEqual(self.backend.keySummary['count'], 11)
        self.assertEqual(self.backend.keyVisibleRows[0]['answer'], '007')
        self.backend.addVariant('2')
        self.backend.setTaskCount(10)
        self.backend.selectKeyVariant('demo')
        self.assertEqual(self.backend.keySummary['count'], 11)
        for index, row in enumerate(self.backend.key_rows):
            if not row['answer']:
                self.backend.editKeyCell(index, 'answer', '7')
        self.assertTrue(self.backend.applyKeys(False))
        self.backend.setVariant('demo', False)
        self.assertEqual(self.backend.format_for('answer_01')['type'], 'mixed')
        self.backend.session.key['variants']['demo']['1']['format'] = dict(type='digits', max_length=2)
        self.backend.editField('А07')
        self.assertIn('Ожидается', self.backend.state['selected']['warning'])
        self.backend.beginKeys()
        self.backend.selectKeySubject('chemistry')
        self.assertEqual(self.backend.keyVisibleRows[0]['answer'], '007')
        self.assertEqual(self.backend.keyVisibleRows[0]['type'], 'digits')
        self.assertEqual(self.backend.keySummary['fullMaximum'], 38)

    def test_progress_theme_duplicates_and_error_recovery(self):
        engine = create_window(app, self.backend)
        root = engine.rootObjects()[0]
        progress = root.findChild(QObject, 'progressWindow')
        self.assertIsNotNone(progress)
        released = Event()
        try:
            self.assertTrue(self.backend.run_operation('test', 'Проверка…', lambda: released.wait(10)))
            app.processEvents()
            self.assertTrue(progress.property('visible'))
            self.assertEqual(progress.property('color'), root.property('surfaceColor'))
            self.assertFalse(self.backend.run_operation('test', 'Дубль', lambda: self.fail('Duplicate operation')))
            self.backend.setDarkTheme(not self.backend.darkTheme)
            app.processEvents()
            self.assertEqual(progress.property('color'), root.property('surfaceColor'))
        finally:
            released.set()
            self.wait_worker()
            self.backend.session.dirty = False
            root.close()
            engine.deleteLater()
            app.processEvents()
        def fail():
            raise ValueError('Ошибка экспорта')
        self.backend.run_operation('export', 'Excel…', fail)
        self.backend.worker.wait(10000)
        app.processEvents()
        self.assertFalse(self.backend.busy)
        self.assertEqual(self.errors, ['Ошибка экспорта'])

    def test_failed_page_retains_reason(self):
        self.backend.session.data['pages'].append(dict(page=36, status='needs_review', fields=[], error='Missing markers'))
        self.backend.selectPage(36)
        self.assertEqual(self.backend.state['pageError'], 'Missing markers')
        self.assertEqual(self.backend.state['results'][1]['total'], '—')

    def test_theme_persists_without_changing_project(self):
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / 'settings.ini')
            first = Backend(QSettings(path, QSettings.IniFormat))
            self.assertTrue(first.darkTheme)
            first.setDarkTheme(False)
            second = Backend(QSettings(path, QSettings.IniFormat))
            self.assertFalse(second.darkTheme)
            second.setDarkTheme(True)
            self.assertTrue(Backend(QSettings(path, QSettings.IniFormat)).darkTheme)

    def test_qml_reacts_to_theme_switch(self):
        with tempfile.TemporaryDirectory() as temp:
            backend = Backend(QSettings(str(Path(temp) / 'theme.ini'), QSettings.IniFormat))
            engine = create_window(app, backend)
            root = engine.rootObjects()[0]
            app.processEvents()
            dark = root.property('backgroundColor')
            toggle = root.findChild(QObject, 'themeToggle')
            self.assertIsNotNone(toggle)
            backend.setDarkTheme(False)
            app.processEvents()
            self.assertNotEqual(root.property('backgroundColor'), dark)
            backend.setDarkTheme(True)
            app.processEvents()
            self.assertEqual(root.property('backgroundColor'), dark)
            root.close()
            engine.deleteLater()
            app.processEvents()

    @unittest.skipUnless(Path('data/raw/full_pdf.pdf').exists(), 'Local dataset required')
    def test_pdf_worker_keeps_event_loop_responsive(self):
        with tempfile.TemporaryDirectory() as temp:
            self.backend.start_worker(Path('data/raw/full_pdf.pdf'), Path(temp) / 'project', [1])
            deadline = time.monotonic() + 60
            ticks = 0
            while self.backend.busy and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.01)
                ticks += 1
            self.backend.worker.wait(10000)
            app.processEvents()
            self.assertFalse(self.backend.busy)
            self.assertFalse(self.errors)
            self.assertGreater(ticks, 2)
            self.assertEqual(len(self.backend.page()['fields']), 23)
