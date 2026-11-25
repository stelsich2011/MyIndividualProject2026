import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from .qt_backend import Backend


def create_window(app, backend):
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('backend', backend)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).with_name('qml') / 'Main.qml')))
    if not engine.rootObjects():
        raise RuntimeError('Не удалось загрузить интерфейс QML')
    return engine


def main():
    parser = argparse.ArgumentParser(description='Проверка бланков ОГЭ — Qt Quick')
    parser.add_argument('--project', type=Path)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--self-test-report', type=Path)
    parser.add_argument('--self-test-pdf', type=Path)
    parser.add_argument('--self-test-pages', default='1')
    args = parser.parse_args()
    QQuickStyle.setStyle('Basic')
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName('Проверка бланков ОГЭ')
    backend = Backend()
    engine = create_window(app, backend)
    if args.project:
        backend.openPath(str(args.project))
    if args.self_test:
        result = {'ok': False}
        def check():
            try:
                import cv2
                import numpy as np
                from .recognize import LocalOCR, normalize, recognize
                from .pipeline import prepare
                from .session import Session
                from .__main__ import parse_pages
                from .keys import write_template, load_key
                image = np.full((80, 240, 3), 255, np.uint8)
                cv2.putText(image, '123', (15, 58), cv2.FONT_HERSHEY_SIMPLEX, 1.8, (0, 0, 0), 3)
                ocr = LocalOCR()
                raw, _ = ocr.read(image)
                assert normalize(raw) == '123', raw
                with tempfile.TemporaryDirectory(prefix='oge-qt-') as temporary:
                    folder = Path(temporary) / 'Проверка с пробелами'
                    folder.mkdir()
                    data = {'run_status': 'complete', 'source_id': 'test', 'source_manifest': '', 'pages': []}
                    if args.self_test_pdf:
                        prepare(args.self_test_pdf, folder / 'prepared', parse_pages(args.self_test_pages))
                        data = recognize(folder / 'prepared', folder / 'ocr', engine=ocr)
                        assert all(p['status'] == 'prepared' and len(p['fields']) == 23 for p in data['pages'])
                    session = Session(data, folder / 'ocr')
                    write_template(folder / 'ключи.xlsx')
                    session.set_key(load_key(folder / 'ключи.xlsx'))
                    session.save(folder / 'project.json')
                    assert backend.openPath(str(folder / 'project.json'))
                    session.export_excel(folder / 'результаты.xlsx')
                result.update(ok=True, ocr=raw, model_path=ocr.model_path, pdf_checked=bool(args.self_test_pdf), pdf_pages=args.self_test_pages, ui='PySide6 / Qt Quick')
            except Exception as exc:
                result['error'] = str(exc)
            if args.self_test_report:
                args.self_test_report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            app.exit(0 if result['ok'] else 1)
        QTimer.singleShot(100, check)
    code = app.exec()
    engine.deleteLater()
    return code


if __name__ == '__main__':
    sys.exit(main())
