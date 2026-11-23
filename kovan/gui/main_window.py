from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import httpx
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui.runtime import LocalRuntime, lan_ip
from gui.theme import ACCENT, BAD, GOOD, INFO, MUTED
from gui.widgets import DeviceCard, StatCard, qr_pixmap, repolish

STATUS_TR = {
    "queued": "Bekliyor",
    "running": "Çalışıyor",
    "completed": "Bitti",
    "failed": "Hata",
}
STATUS_COLOR = {
    "queued": MUTED,
    "running": INFO,
    "completed": GOOD,
    "failed": BAD,
}
TASK_NAME_TR = {
    "word_count": "Kelime say",
    "sha256_file": "Dosya SHA-256",
    "pi_monte_carlo": "π (Monte Carlo)",
    "prime_count": "Asal sayma",
}
MAX_MC = 50_000_000


class Poller(QThread):
    updated = Signal(object, object, str)

    def __init__(self, runtime: LocalRuntime) -> None:
        super().__init__()
        self.runtime = runtime
        self._running = True

    def run(self) -> None:
        with self.runtime.client() as client:
            while self._running:
                devices: list = []
                tasks: list = []
                error = ""
                try:
                    response = client.get("/devices")
                    response.raise_for_status()
                    devices = response.json()
                    response = client.get("/tasks", params={"limit": 300})
                    response.raise_for_status()
                    tasks = response.json()
                except httpx.HTTPError as exc:
                    error = str(exc) or exc.__class__.__name__
                self.updated.emit(devices, tasks, error)

                for _ in range(15):
                    if not self._running:
                        return
                    self.msleep(100)

    def stop(self) -> None:
        self._running = False
        self.wait(3000)


def make_table(headers: list[str], stretch_last: bool = True) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    table.setShowGrid(False)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(38)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    if stretch_last:
        header.setSectionResizeMode(
            len(headers) - 1, QHeaderView.ResizeMode.Stretch
        )
    header.setHighlightSections(False)
    header.setDefaultAlignment(
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    )
    return table


def page_header(title: str, subtitle: str) -> QWidget:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 6)
    layout.setSpacing(2)
    heading = QLabel(title)
    heading.setObjectName("h1")
    sub = QLabel(subtitle)
    sub.setObjectName("muted")
    layout.addWidget(heading)
    layout.addWidget(sub)
    return widget


def card(layout: QVBoxLayout | QGridLayout | QFormLayout | QHBoxLayout) -> QFrame:
    frame = QFrame()
    frame.setObjectName("card")
    layout.setContentsMargins(20, 18, 20, 18)
    frame.setLayout(layout)
    return frame


def make_page() -> tuple[QWidget, QVBoxLayout]:
    page = QWidget()
    page.setObjectName("page")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(28, 24, 28, 20)
    layout.setSpacing(14)
    return page, layout


class MainWindow(QMainWindow):
    def __init__(self, runtime: LocalRuntime) -> None:
        super().__init__()
        self.rt = runtime
        self.setWindowTitle("KOVAN")
        self.resize(1180, 760)
        self.setMinimumSize(980, 640)

        self.device_cards: dict[str, DeviceCard] = {}
        self.last_tasks: list[dict] = []
        self.bench: dict | None = None
        self.bench_history: list[dict] = []
        self.pair_expires = 0.0
        self.pair_code = ""

        root = QWidget()
        root.setObjectName("root")
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_dashboard())
        self.stack.addWidget(self._build_tasks_page())
        self.stack.addWidget(self._build_new_task_page())
        self.stack.addWidget(self._build_bench_page())
        self.stack.addWidget(self._build_connect_page())
        self.stack.currentChanged.connect(self._page_changed)
        outer.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        self.nav_buttons[0].setChecked(True)

        self.pair_timer = QTimer(self)
        self.pair_timer.timeout.connect(self._tick_pairing)
        self.pair_timer.start(1000)

        self.poller = Poller(runtime)
        self.poller.updated.connect(self.on_update)
        self.poller.start()

    # ------------------------------------------------------------ iskelet
    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 22, 14, 16)
        layout.setSpacing(4)

        logo = QLabel("⬡  KOVAN")
        logo.setObjectName("logo")
        tagline = QLabel("Dağıtık hesaplama")
        tagline.setObjectName("tagline")
        layout.addWidget(logo)
        layout.addWidget(tagline)
        layout.addSpacing(18)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: list[QPushButton] = []
        entries = [
            "▦   Panel",
            "☰   Görevler",
            "＋   Yeni görev",
            "⏱   Benchmark",
            "⇄   Cihaz bağla",
        ]
        for index, text in enumerate(entries):
            button = QPushButton(text)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda _checked=False, i=index: self.stack.setCurrentIndex(i)
            )
            self.nav_group.addButton(button, index)
            self.nav_buttons.append(button)
            layout.addWidget(button)

        layout.addStretch(1)
        self.conn_label = QLabel("Başlıyor…")
        self.conn_label.setObjectName("muted")
        self.conn_label.setWordWrap(True)
        layout.addWidget(self.conn_label)
        return sidebar

    def _page_changed(self, index: int) -> None:
        self.nav_buttons[index].setChecked(True)
        if index == 4:
            self.refresh_pairing(force=False)

    # ------------------------------------------------------------ panel
    def _build_dashboard(self) -> QWidget:
        page, layout = make_page()
        layout.addWidget(page_header("Panel", "Kümedeki cihazlar ve görevler"))

        stats = QHBoxLayout()
        stats.setSpacing(14)
        self.stat_devices = StatCard("Cihazlar", ACCENT)
        self.stat_queued = StatCard("Bekleyen", MUTED)
        self.stat_running = StatCard("Çalışan", INFO)
        self.stat_done = StatCard("Tamamlanan", GOOD)
        for stat in (
            self.stat_devices, self.stat_queued,
            self.stat_running, self.stat_done,
        ):
            stats.addWidget(stat)
        layout.addLayout(stats)

        title = QLabel("Cihazlar")
        title.setObjectName("h2")
        layout.addWidget(title)

        self.empty_label = QLabel("Henüz bağlı cihaz yok. “Cihaz bağla” sayfasından ekleyebilirsin.")
        self.empty_label.setObjectName("muted")
        layout.addWidget(self.empty_label)

        self.cards_host = QWidget()
        self.cards_layout = QGridLayout(self.cards_host)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(14)
        self.cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.cards_host)
        scroll.setMinimumHeight(300)
        layout.addWidget(scroll, 1)

        recent_title = QLabel("Son görevler")
        recent_title.setObjectName("h2")
        layout.addWidget(recent_title)
        self.recent_table = make_table(
            ["ID", "Tür", "Durum", "Cihaz", "Sonuç / Hata"]
        )
        self.recent_table.setFixedHeight(38 * 4 + 40)
        layout.addWidget(self.recent_table)
        return page

    # ------------------------------------------------------------ görevler
    def _build_tasks_page(self) -> QWidget:
        page, layout = make_page()
        layout.addWidget(page_header("Görevler", "Kuyruk ve sonuçlar"))

        bar = QHBoxLayout()
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(
            ["Tümü", "Bekleyen", "Çalışan", "Biten", "Hatalı"]
        )
        self.filter_combo.currentIndexChanged.connect(
            lambda _i: self._fill_tasks()
        )
        bar.addWidget(self.filter_combo)
        bar.addStretch(1)
        layout.addLayout(bar)

        self.tasks_table = make_table(
            ["ID", "Tür", "Durum", "Cihaz", "Deneme", "Öncelik", "Sonuç / Hata"]
        )
        layout.addWidget(self.tasks_table, 1)
        return page

    # ------------------------------------------------------------ yeni görev
    def _build_new_task_page(self) -> QWidget:
        page, layout = make_page()
        layout.addWidget(
            page_header("Yeni görev", "Kuyruğa tek bir iş ekle veya demo çalıştır")
        )

        self.kind_combo = QComboBox()
        self.kind_combo.addItems(
            [
                "Kelime say (metin)",
                "Kelime say (dosya)",
                "Dosya SHA-256",
                "π tahmini (Monte Carlo)",
                "Asal sayma",
            ]
        )
        self.kind_combo.currentIndexChanged.connect(self._kind_changed)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText("Kelimeleri sayılacak metin…")
        self.text_edit.setFixedHeight(110)

        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Dosya yolu (data/ klasöründe olmalı)")
        browse = QPushButton("Seç…")
        browse.clicked.connect(self.pick_file)
        path_row = QHBoxLayout()
        path_row.setContentsMargins(0, 0, 0, 0)
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse)
        self.path_widget = QWidget()
        self.path_widget.setLayout(path_row)

        self.pi_samples = QSpinBox()
        self.pi_samples.setRange(1, MAX_MC // 1000)
        self.pi_samples.setValue(2000)
        self.pi_samples.setSuffix(" bin örnek")
        self.pi_samples.setGroupSeparatorShown(True)
        self.prime_start = QSpinBox()
        self.prime_start.setRange(0, 49_000_000)
        self.prime_start.setGroupSeparatorShown(True)
        self.prime_stop = QSpinBox()
        self.prime_stop.setRange(1, 50_000_000)
        self.prime_stop.setValue(1_000_000)
        self.prime_stop.setGroupSeparatorShown(True)
        compute_form = QFormLayout()
        compute_form.setContentsMargins(0, 0, 0, 0)
        compute_form.addRow("π örnek sayısı", self.pi_samples)
        compute_form.addRow("Asal aralığı başı", self.prime_start)
        compute_form.addRow("Asal aralığı sonu", self.prime_stop)
        self.compute_widget = QWidget()
        self.compute_widget.setLayout(compute_form)

        self.priority_spin = QSpinBox()
        self.priority_spin.setRange(0, 100)
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(5, 3600)
        self.timeout_spin.setValue(60)
        self.timeout_spin.setSuffix(" sn")

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        form.addRow("Görev türü", self.kind_combo)
        form.addRow("Metin", self.text_edit)
        form.addRow("Dosya", self.path_widget)
        form.addRow("Parametreler", self.compute_widget)
        form.addRow("Öncelik (0–100)", self.priority_spin)
        form.addRow("Zaman aşımı", self.timeout_spin)
        self._form = form
        layout.addWidget(card(form))

        send = QPushButton("Görevi gönder")
        send.setObjectName("primary")
        send.clicked.connect(self.submit_task)
        demo = QPushButton("Demo: 10 örnek görev gönder")
        demo.clicked.connect(self.submit_demo)
        buttons = QHBoxLayout()
        buttons.addWidget(send)
        buttons.addWidget(demo)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.result_label = QLabel("")
        self.result_label.setObjectName("muted")
        self.result_label.setWordWrap(True)
        layout.addWidget(self.result_label)
        layout.addStretch(1)
        self._kind_changed(0)
        return page

    # ------------------------------------------------------------ benchmark
    def _build_bench_page(self) -> QWidget:
        page, layout = make_page()
        layout.addWidget(
            page_header(
                "Benchmark",
                "Aynı π hesabını 1 cihazda ve tüm cihazlarda çalıştırıp süreyi karşılaştır",
            )
        )

        self.bench_total = QSpinBox()
        self.bench_total.setRange(10, 2000)
        self.bench_total.setValue(100)
        self.bench_total.setSuffix(" milyon örnek")
        self.bench_chunks = QSpinBox()
        self.bench_chunks.setRange(4, 200)
        self.bench_chunks.setValue(50)
        self.bench_chunks.setSuffix(" parça")
        self.bench_target = QComboBox()
        self.bench_target.addItems(["Tüm cihazlar", "Sadece bu bilgisayar"])
        self.bench_button = QPushButton("Benchmark'ı başlat")
        self.bench_button.setObjectName("primary")
        self.bench_button.clicked.connect(self.start_bench)

        controls = QHBoxLayout()
        for label, widget in (
            ("Toplam", self.bench_total),
            ("Parça", self.bench_chunks),
            ("Hedef", self.bench_target),
        ):
            column = QVBoxLayout()
            caption = QLabel(label)
            caption.setObjectName("muted")
            column.addWidget(caption)
            column.addWidget(widget)
            controls.addLayout(column)
        controls.addStretch(1)
        controls.addWidget(self.bench_button, 0, Qt.AlignmentFlag.AlignBottom)
        layout.addWidget(card(controls))

        self.bench_result = QLabel("Henüz çalıştırılmadı")
        self.bench_result.setObjectName("bench")
        self.bench_sub = QLabel("")
        self.bench_sub.setObjectName("muted")
        self.bench_bar = QProgressBar()
        self.bench_bar.setTextVisible(False)
        result_layout = QVBoxLayout()
        result_layout.setSpacing(8)
        result_layout.addWidget(self.bench_result)
        result_layout.addWidget(self.bench_bar)
        result_layout.addWidget(self.bench_sub)
        layout.addWidget(card(result_layout))

        tables = QHBoxLayout()
        tables.setSpacing(14)
        left = QVBoxLayout()
        left_title = QLabel("Cihaz başına katkı (son çalıştırma)")
        left_title.setObjectName("h2")
        self.bench_devices = make_table(["Cihaz", "Parça", "Ort. süre / parça"])
        left.addWidget(left_title)
        left.addWidget(self.bench_devices)
        right = QVBoxLayout()
        right_title = QLabel("Çalıştırma geçmişi")
        right_title.setObjectName("h2")
        self.bench_table = make_table(
            ["#", "Hedef", "Cihaz", "Süre", "π", "Hız"]
        )
        right.addWidget(right_title)
        right.addWidget(self.bench_table)
        tables.addLayout(left, 1)
        tables.addLayout(right, 1)
        layout.addLayout(tables, 1)
        return page

    # ------------------------------------------------------------ cihaz bağla
    def _build_connect_page(self) -> QWidget:
        page, layout = make_page()
        layout.addWidget(
            page_header("Cihaz bağla", "Telefonunu veya başka bir bilgisayarı kümeye kat")
        )

        self.lan_banner = QLabel("")
        self.lan_banner.setObjectName("banner")
        self.lan_banner.setWordWrap(True)
        self.lan_button = QPushButton("Ağ erişimini aç")
        self.lan_button.setObjectName("primary")
        self.lan_button.clicked.connect(self.enable_lan)
        banner_row = QHBoxLayout()
        banner_row.addWidget(self.lan_banner, 1)
        banner_row.addWidget(self.lan_button)
        layout.addLayout(banner_row)

        # Telefon kartı
        self.qr_label = QLabel()
        self.qr_label.setFixedSize(300, 300)
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setStyleSheet("background: white; border-radius: 12px;")
        self.code_label = QLabel("—")
        self.code_label.setObjectName("code")
        self.expiry_label = QLabel("")
        self.expiry_label.setObjectName("muted")
        self.url_label = QLabel("")
        self.url_label.setObjectName("mono")
        self.url_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.url_label.setWordWrap(True)
        new_code = QPushButton("Yeni kod üret")
        new_code.clicked.connect(lambda: self.refresh_pairing(force=True))

        steps = QLabel(
            "<b>1.</b> Telefon ve bilgisayar aynı Wi-Fi ağında olsun.<br>"
            "<b>2.</b> Telefonun kamerasıyla QR kodu okut, açılan bağlantıya dokun.<br>"
            "<b>3.</b> Sayfa otomatik bağlanır. Kodu elle girmek istersen "
            "adresi aç ve aşağıdaki kodu yaz.<br><br>"
            "<span style='color:#8b95a5'>Telefon, sayfa açık ve ekran uyanıkken "
            "görev alır. Pil bilgisi şifresiz HTTP'de tarayıcıdan okunamaz; bu "
            "yüzden telefona yalnızca hafif görevler verilir.</span>"
        )
        steps.setWordWrap(True)
        steps.setTextFormat(Qt.TextFormat.RichText)

        info = QVBoxLayout()
        info.setSpacing(8)
        phone_title = QLabel("📱  Telefon / tablet")
        phone_title.setObjectName("h2")
        info.addWidget(phone_title)
        info.addWidget(steps)
        info.addSpacing(6)
        info.addWidget(self.code_label)
        info.addWidget(self.expiry_label)
        info.addWidget(self.url_label)
        info.addWidget(new_code, 0, Qt.AlignmentFlag.AlignLeft)
        info.addStretch(1)

        phone_row = QHBoxLayout()
        phone_row.setSpacing(24)
        phone_row.addWidget(self.qr_label, 0, Qt.AlignmentFlag.AlignTop)
        phone_row.addLayout(info, 1)
        self.phone_card = card(phone_row)
        layout.addWidget(self.phone_card)

        # Bilgisayar kartı
        self.pc_text = QPlainTextEdit()
        self.pc_text.setReadOnly(True)
        self.pc_text.setFixedHeight(150)
        font = self.pc_text.font()
        font.setFamily("Consolas")
        self.pc_text.setFont(font)
        copy_button = QPushButton("Kayıt token'ını panoya kopyala")
        copy_button.clicked.connect(self.copy_registration_token)
        self.copy_label = QLabel("")
        self.copy_label.setObjectName("good")
        pc_title = QLabel("💻  Bilgisayar / laptop")
        pc_title.setObjectName("h2")
        pc_layout = QVBoxLayout()
        pc_layout.setSpacing(8)
        pc_layout.addWidget(pc_title)
        pc_layout.addWidget(self.pc_text)
        copy_row = QHBoxLayout()
        copy_row.addWidget(copy_button)
        copy_row.addWidget(self.copy_label)
        copy_row.addStretch(1)
        pc_layout.addLayout(copy_row)
        self.pc_card = card(pc_layout)
        layout.addWidget(self.pc_card)
        layout.addStretch(1)
        self._update_connect_state()
        return page

    # ------------------------------------------------------------ eylemler
    def _kind_changed(self, index: int) -> None:
        mapping = {
            0: self.text_edit,
            1: self.path_widget,
            2: self.path_widget,
            3: self.compute_widget,
            4: self.compute_widget,
        }
        visible = mapping[index]
        for widget in (self.text_edit, self.path_widget, self.compute_widget):
            self._form.setRowVisible(widget, widget is visible)
        if index in (3, 4):
            self.pi_samples.setEnabled(index == 3)
            self.prime_start.setEnabled(index == 4)
            self.prime_stop.setEnabled(index == 4)

    def copy_registration_token(self) -> None:
        QGuiApplication.clipboard().setText(self.rt.registration_token)
        self.copy_label.setText("Kopyalandı")

    def pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Dosya seç", str(self.rt.data_dir)
        )
        if not path:
            return

        chosen = Path(path).resolve()
        if not chosen.is_relative_to(self.rt.data_dir):
            answer = QMessageBox.question(
                self,
                "Dosya kopyalansın mı?",
                "Yerel worker güvenlik için yalnızca data/ klasöründeki "
                "dosyaları okuyabilir.\nDosya data/ içine kopyalansın mı?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            destination = self.rt.data_dir / chosen.name
            counter = 1
            while destination.exists():
                destination = self.rt.data_dir / (
                    f"{chosen.stem}-{counter}{chosen.suffix}"
                )
                counter += 1
            shutil.copy2(chosen, destination)
            chosen = destination
        self.path_edit.setText(str(chosen))

    def _post_tasks(self, bodies: list[dict]) -> list[int]:
        ids: list[int] = []
        with self.rt.client() as client:
            for body in bodies:
                response = client.post("/tasks", json=body)
                if response.status_code != 200:
                    raise RuntimeError(response.text)
                ids.append(int(response.json()["task_id"]))
        return ids

    def submit_task(self) -> None:
        index = self.kind_combo.currentIndex()
        requirements: dict = {"priority": self.priority_spin.value()}

        if index == 0:
            text = self.text_edit.toPlainText()
            if not text.strip():
                self.result_label.setText("Önce bir metin yaz.")
                return
            task_type, payload = "word_count", {"text": text}
        elif index in (1, 2):
            path = self.path_edit.text().strip()
            if not path:
                self.result_label.setText("Önce bir dosya seç.")
                return
            task_type = "word_count" if index == 1 else "sha256_file"
            payload = {"path": path}
            requirements["allowed_device_ids"] = [self.rt.device_id]
        elif index == 3:
            task_type = "pi_monte_carlo"
            payload = {"samples": self.pi_samples.value() * 1000, "seed": 1}
        else:
            start, stop = self.prime_start.value(), self.prime_stop.value()
            if stop <= start or stop - start > 5_000_000:
                self.result_label.setText(
                    "Aralık geçersiz: son > baş olmalı ve en fazla 5 milyon geniş olabilir."
                )
                return
            task_type, payload = "prime_count", {"start": start, "stop": stop}

        body = {
            "task_type": task_type,
            "payload": payload,
            "requirements": requirements,
            "timeout_seconds": self.timeout_spin.value(),
        }
        try:
            (task_id,) = self._post_tasks([body])
        except Exception as exc:
            self.result_label.setText(f"Gönderilemedi: {exc}")
            return
        self.result_label.setText(f"Görev #{task_id} kuyruğa eklendi.")

    def submit_demo(self) -> None:
        bodies = [
            {
                "task_type": "word_count",
                "payload": {"text": ("kovan demo " * 2000) + str(number)},
                "requirements": {"priority": 0},
            }
            for number in range(10)
        ]
        try:
            ids = self._post_tasks(bodies)
        except Exception as exc:
            self.result_label.setText(f"Gönderilemedi: {exc}")
            return
        self.result_label.setText(f"{len(ids)} demo görev eklendi.")

    def remove_device(self, device_id: str) -> None:
        answer = QMessageBox.question(
            self,
            "Cihaz kaldırılsın mı?",
            f"“{device_id}” listeden kaldırılacak. Çalışan görevi varsa "
            "başka cihaza verilir.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        with self.rt.client() as client:
            client.delete(f"/devices/{device_id}")

    # ------------------------------------------------------------ benchmark
    def start_bench(self) -> None:
        total = self.bench_total.value() * 1_000_000
        chunks = max(self.bench_chunks.value(), -(-total // MAX_MC))
        chunks = min(chunks, 200)
        per_chunk = total // chunks
        if per_chunk > MAX_MC:
            self.bench_sub.setText("Toplam örnek bu parça sayısıyla çok büyük.")
            return

        local_only = self.bench_target.currentIndex() == 1
        requirements: dict = {"priority": 10}
        if local_only:
            requirements["allowed_device_ids"] = [self.rt.device_id]

        bodies = [
            {
                "task_type": "pi_monte_carlo",
                "payload": {"samples": per_chunk, "seed": index + 1},
                "requirements": requirements,
                "timeout_seconds": 180,
            }
            for index in range(chunks)
        ]
        try:
            ids = self._post_tasks(bodies)
        except Exception as exc:
            self.bench_sub.setText(f"Gönderilemedi: {exc}")
            return

        self.bench = {
            "ids": set(ids),
            "local_only": local_only,
            "samples": per_chunk * chunks,
        }
        self.bench_button.setEnabled(False)
        self.bench_bar.setMaximum(len(ids))
        self.bench_bar.setValue(0)
        self.bench_result.setText("Çalışıyor…")
        self.bench_sub.setText(f"{len(ids)} parça kuyruğa eklendi.")

    def _update_bench(self) -> None:
        bench = self.bench
        if not bench:
            return
        mine = [t for t in self.last_tasks if t["id"] in bench["ids"]]
        done = [t for t in mine if t["status"] == "completed"]
        failed = [t for t in mine if t["status"] == "failed"]
        finished = len(done) + len(failed)
        self.bench_bar.setValue(finished)
        if len(mine) < len(bench["ids"]) or finished < len(bench["ids"]):
            self.bench_sub.setText(
                f"{len(done)}/{len(bench['ids'])} parça tamamlandı"
            )
            return
        if not done:
            self.bench_result.setText("Tüm parçalar başarısız oldu")
            self.bench_button.setEnabled(True)
            self.bench = None
            return

        duration = max(t["updated_at"] for t in done) - min(
            t["created_at"] for t in mine
        )
        inside = sum(t["result"]["inside"] for t in done)
        samples = sum(t["result"]["samples"] for t in done)
        pi_value = 4 * inside / samples
        per_device: dict[str, list[float]] = {}
        for task in done:
            per_device.setdefault(task["assigned_worker"] or "?", []).append(
                float(task["result"].get("elapsed_seconds", 0))
            )

        record = {
            "target": "Sadece bu bilgisayar" if bench["local_only"] else "Tüm cihazlar",
            "local_only": bench["local_only"],
            "devices": len(per_device),
            "duration": duration,
            "pi": pi_value,
        }
        baseline = next(
            (r for r in self.bench_history if r["local_only"]), None
        )
        speed = ""
        ratio = 1.0
        if baseline and not record["local_only"] and duration > 0:
            ratio = baseline["duration"] / duration
            speed = f"{ratio:.1f}×"
        record["speed"] = speed
        self.bench_history.append(record)

        text = f"π ≈ {pi_value:.5f}   •   {duration:.1f} sn   •   {len(per_device)} cihaz"
        if speed:
            text += f"   •   {speed} " + ("daha hızlı" if ratio >= 1 else "daha yavaş")
        self.bench_result.setText(text)
        note = f"{samples / 1e6:.0f} milyon örnek"
        if failed:
            note += f" • {len(failed)} parça başarısız"
        self.bench_sub.setText(note)

        self.bench_devices.setRowCount(len(per_device))
        for row, (name, times) in enumerate(sorted(per_device.items())):
            self._set_cell(self.bench_devices, row, 0, name)
            self._set_cell(self.bench_devices, row, 1, str(len(times)))
            self._set_cell(
                self.bench_devices, row, 2, f"{sum(times) / len(times):.2f} sn"
            )
        self.bench_table.setRowCount(len(self.bench_history))
        for row, rec in enumerate(self.bench_history):
            values = [
                str(row + 1), rec["target"], str(rec["devices"]),
                f"{rec['duration']:.1f} sn", f"{rec['pi']:.5f}", rec["speed"] or "—",
            ]
            for col, value in enumerate(values):
                self._set_cell(self.bench_table, row, col, value)

        self.bench_button.setEnabled(True)
        self.bench = None

    # ------------------------------------------------------------ bağlantı
    def _update_connect_state(self) -> None:
        lan = self.rt.lan
        ip = lan_ip()
        if lan:
            where = f"http://{ip}:{self.rt.port}" if ip else f"port {self.rt.port}"
            self.lan_banner.setText(
                f"Ağ erişimi AÇIK  •  {where}\n"
                "İletişim şifresiz HTTP'dir; yalnızca güvenilir ev ağında kullan."
            )
        else:
            self.lan_banner.setText(
                "Ağ erişimi KAPALI. Telefon veya başka bir bilgisayar "
                "bağlamak için önce açman gerekir."
            )
        self.lan_banner.setProperty("ok", "true" if lan else "false")
        repolish(self.lan_banner)
        self.lan_button.setVisible(not lan)
        self.phone_card.setVisible(lan)
        self.pc_card.setVisible(lan)

        if lan:
            address = f"http://{ip or '<bu-bilgisayarın-ip-adresi>'}:{self.rt.port}"
            self.pc_text.setPlainText(
                "Diğer bilgisayarda (proje klasörü ve paketler hazır), PowerShell:\n\n"
                f'$env:KOVAN_CONTROLLER_URL = "{address}"\n'
                '$env:KOVAN_DEVICE_ID = "laptop-1"\n'
                '$env:KOVAN_DEVICE_TYPE = "laptop"\n'
                '$env:KOVAN_REGISTRATION_TOKEN = "<KAYIT_TOKENI>"\n'
                "New-Item -ItemType Directory data -Force | Out-Null\n"
                '$env:KOVAN_ALLOWED_DIRS = (Resolve-Path .\\data).Path\n'
                "python -m worker.main"
            )

    def enable_lan(self) -> None:
        answer = QMessageBox.question(
            self,
            "Ağ erişimi açılsın mı?",
            "Controller ev ağındaki cihazlara açılacak. İletişim şifresiz "
            "HTTP'dir; yalnızca güvenilir ağında kullan.\n\n"
            "Windows güvenlik duvarı sorarsa “Özel ağlar”a izin ver.\n\n"
            "Devam edilsin mi?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.rt.set_lan(True)
        except Exception as exc:
            QMessageBox.critical(self, "Açılamadı", str(exc))
            return
        self._update_connect_state()
        self.refresh_pairing(force=True)

    def refresh_pairing(self, *, force: bool) -> None:
        self._update_connect_state()
        if not self.rt.lan:
            return
        if not force and self.pair_code and time.time() < self.pair_expires - 5:
            return
        try:
            with self.rt.client() as client:
                response = client.post("/pairing-codes")
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            self.expiry_label.setText(f"Kod alınamadı: {exc}")
            return

        self.pair_code = data["code"]
        self.pair_expires = time.time() + int(data["expires_in"])
        ip = lan_ip()
        if ip:
            url = f"http://{ip}:{self.rt.port}/phone#c={self.pair_code}"
            self.qr_label.setPixmap(
                qr_pixmap(url, 6).scaled(
                    280, 280,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
            )
            self.url_label.setText(f"http://{ip}:{self.rt.port}/phone")
        else:
            self.qr_label.setText("Ağ adresi bulunamadı")
            self.url_label.setText("")
        self.code_label.setText(self.pair_code)
        self._tick_pairing()

    def _tick_pairing(self) -> None:
        if not self.rt.lan or not self.pair_code:
            return
        remaining = int(self.pair_expires - time.time())
        if remaining <= 0:
            self.expiry_label.setText("Kodun süresi doldu")
            if self.stack.currentIndex() == 4:
                self.refresh_pairing(force=True)
            return
        self.expiry_label.setText(
            f"Kod {remaining // 60}:{remaining % 60:02d} sonra geçersiz olur "
            "(tek kullanımlık)"
        )

    # ------------------------------------------------------------ veri
    def on_update(self, devices: list, tasks: list, error: str) -> None:
        if error:
            self.conn_label.setText(f"● Controller'a ulaşılamıyor\n{error}")
            return

        self.last_tasks = tasks
        online = sum(1 for d in devices if d["connection_status"] == "online")
        counts = {s: 0 for s in STATUS_TR}
        for task in tasks:
            counts[task["status"]] = counts.get(task["status"], 0) + 1

        self.stat_devices.set(f"{online}/{len(devices)}", "çevrimiçi / toplam")
        self.stat_queued.set(str(counts["queued"]), "sırada")
        self.stat_running.set(str(counts["running"]), "şu an")
        self.stat_done.set(str(counts["completed"]), f"{counts['failed']} hata")

        self._fill_devices(devices, tasks)
        self._fill_tasks()
        self._update_bench()

        mode = "ağa açık" if self.rt.lan else "yalnızca bu PC"
        self.conn_label.setText(
            f"● Controller çalışıyor\n{self.rt.base_url}\n{mode}\n\n"
            f"Yerel worker:\n{self.rt.worker_state}"
        )

    @staticmethod
    def _set_cell(table: QTableWidget, row: int, col: int, text: str,
                  color: str | None = None) -> None:
        item = QTableWidgetItem(text)
        if color:
            item.setForeground(QColor(color))
        table.setItem(row, col, item)

    def _fill_devices(self, devices: list, tasks: list) -> None:
        running_by_device = {
            t["assigned_worker"]: t
            for t in tasks
            if t["status"] == "running" and t.get("assigned_worker")
        }
        wanted = {d["device_id"] for d in devices}

        changed = set(self.device_cards) != wanted
        for device_id in list(self.device_cards):
            if device_id not in wanted:
                widget = self.device_cards.pop(device_id)
                self.cards_layout.removeWidget(widget)
                widget.deleteLater()

        for device in devices:
            device_id = device["device_id"]
            widget = self.device_cards.get(device_id)
            if widget is None:
                widget = DeviceCard(
                    device_id, removable=device_id != self.rt.device_id
                )
                widget.removeRequested.connect(self.remove_device)
                self.device_cards[device_id] = widget
            widget.update_from(device, running_by_device.get(device_id))

        if changed:
            for widget in self.device_cards.values():
                self.cards_layout.removeWidget(widget)
            columns = 2
            for position, device_id in enumerate(sorted(self.device_cards)):
                self.cards_layout.addWidget(
                    self.device_cards[device_id],
                    position // columns,
                    position % columns,
                )
            for column in range(columns):
                self.cards_layout.setColumnStretch(column, 1)
        self.empty_label.setVisible(not devices)

    @staticmethod
    def _task_detail(task: dict) -> str:
        if task.get("error"):
            detail = task["error"]
        elif task.get("result") is not None:
            detail = json.dumps(task["result"], ensure_ascii=False)
        else:
            detail = ""
        return detail if len(detail) <= 110 else detail[:107] + "…"

    def _fill_tasks(self) -> None:
        filters = [None, "queued", "running", "completed", "failed"]
        wanted = filters[self.filter_combo.currentIndex()]
        rows = [t for t in self.last_tasks if wanted in (None, t["status"])]

        table = self.tasks_table
        table.setRowCount(len(rows))
        for row, task in enumerate(rows):
            status = task["status"]
            values = [
                str(task["id"]),
                TASK_NAME_TR.get(task["task_type"], task["task_type"]),
                "● " + STATUS_TR.get(status, status),
                task.get("assigned_worker") or "—",
                f"{task['attempt_count']}/{task['max_attempts']}",
                str(task.get("priority", 0)),
                self._task_detail(task),
            ]
            for col, value in enumerate(values):
                color = STATUS_COLOR.get(status) if col == 2 else None
                self._set_cell(table, row, col, value, color)

        recent = self.last_tasks[:4]
        self.recent_table.setRowCount(len(recent))
        for row, task in enumerate(recent):
            status = task["status"]
            values = [
                str(task["id"]),
                TASK_NAME_TR.get(task["task_type"], task["task_type"]),
                "● " + STATUS_TR.get(status, status),
                task.get("assigned_worker") or "—",
                self._task_detail(task),
            ]
            for col, value in enumerate(values):
                color = STATUS_COLOR.get(status) if col == 2 else None
                self._set_cell(self.recent_table, row, col, value, color)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.poller.stop()
        self.pair_timer.stop()
        self.rt.stop()
        super().closeEvent(event)
