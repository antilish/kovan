"""KOVAN'ı arayüzle başlatır: controller + yerel worker + pencere.

PyCharm'da bu dosyaya sağ tıklayıp "Run 'run_kovan'" yeterlidir.
Ağdaki başka cihazların bağlanması için:  python run_kovan.py --lan
"""

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="KOVAN: controller + yerel worker + arayüz"
    )
    parser.add_argument(
        "--lan",
        action="store_true",
        help="Ağdaki diğer cihazların bağlanmasına izin ver "
        "(şifresiz HTTP; yalnızca güvenilir ağda). Arayüzdeki "
        "'Cihaz bağla' sayfasından da açılabilir.",
    )
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--no-worker",
        action="store_true",
        help="Bu bilgisayarda yerel worker başlatma",
    )
    args = parser.parse_args()

    from PySide6.QtWidgets import QApplication, QMessageBox

    from gui.main_window import MainWindow
    from gui.runtime import LocalRuntime
    from gui.theme import apply_theme

    app = QApplication(sys.argv)
    apply_theme(app)
    runtime = LocalRuntime(
        Path(__file__).resolve().parent,
        host="0.0.0.0" if args.lan else None,
        port=args.port,
        run_worker=not args.no_worker,
    )
    try:
        runtime.start()
    except Exception as exc:
        QMessageBox.critical(None, "KOVAN başlatılamadı", str(exc))
        runtime.stop()
        return 1

    window = MainWindow(runtime)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
