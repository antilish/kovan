from __future__ import annotations

import segno
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QToolButton,
    QVBoxLayout,
)

DEVICE_ICONS = {
    "desktop": "🖥",
    "laptop": "💻",
    "mini_pc": "🖥",
    "raspberry_pi": "🍓",
    "phone": "📱",
    "tablet": "📱",
    "microcontroller": "🔌",
    "unknown": "⬡",
}
DEVICE_TYPE_TR = {
    "desktop": "Masaüstü",
    "laptop": "Dizüstü",
    "mini_pc": "Mini PC",
    "raspberry_pi": "Raspberry Pi",
    "phone": "Telefon",
    "tablet": "Tablet",
    "microcontroller": "Mikrodenetleyici",
    "unknown": "Cihaz",
}


def fmt_bytes(value: int | None) -> str:
    if value is None:
        return "—"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return "—"


def qr_pixmap(text: str, scale: int = 7) -> QPixmap:
    matrix = [list(row) for row in segno.make(text, error="m").matrix]
    border = 4
    side = (len(matrix) + 2 * border) * scale
    image = QImage(side, side, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#0b0f14"))
    for y, row in enumerate(matrix):
        for x, value in enumerate(row):
            if value:
                painter.drawRect(
                    (x + border) * scale, (y + border) * scale, scale, scale
                )
    painter.end()
    return QPixmap.fromImage(image)


def repolish(widget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class StatCard(QFrame):
    def __init__(self, title: str, accent: str) -> None:
        super().__init__()
        self.setObjectName("card")
        self.value = QLabel("0")
        self.value.setObjectName("stat")
        self.value.setStyleSheet(f"color: {accent};")
        self.title = QLabel(title)
        self.title.setObjectName("h2")
        self.sub = QLabel("")
        self.sub.setObjectName("muted")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(2)
        layout.addWidget(self.title)
        layout.addWidget(self.value)
        layout.addWidget(self.sub)

    def set(self, value: str, sub: str = "") -> None:
        self.value.setText(value)
        self.sub.setText(sub)


class DeviceCard(QFrame):
    removeRequested = Signal(str)

    def __init__(self, device_id: str, removable: bool) -> None:
        super().__init__()
        self.setObjectName("card")
        self.device_id = device_id
        self.setMinimumWidth(320)

        self.icon = QLabel("⬡")
        self.icon.setObjectName("icon")
        self.name = QLabel(device_id)
        self.name.setObjectName("h2")
        self.kind = QLabel("")
        self.kind.setObjectName("muted")
        self.kind.setWordWrap(True)
        self.chip = QLabel("")

        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(self.name)
        titles.addWidget(self.kind)

        top = QHBoxLayout()
        top.addWidget(self.icon)
        top.addLayout(titles, 1)
        top.addWidget(self.chip)
        if removable:
            remove = QToolButton()
            remove.setText("✕")
            remove.setToolTip("Cihazı listeden kaldır")
            remove.clicked.connect(lambda: self.removeRequested.emit(device_id))
            top.addWidget(remove)

        self.cpu_label = QLabel("CPU")
        self.cpu_label.setObjectName("muted")
        self.cpu_bar = QProgressBar()
        self.cpu_bar.setTextVisible(False)
        self.ram_label = QLabel("RAM")
        self.ram_label.setObjectName("muted")
        self.ram_bar = QProgressBar()
        self.ram_bar.setTextVisible(False)
        self.battery_label = QLabel("Pil")
        self.battery_label.setObjectName("muted")
        self.battery_bar = QProgressBar()
        self.battery_bar.setTextVisible(False)
        self.activity = QLabel("Boşta")
        self.activity.setObjectName("muted")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(5)
        layout.addLayout(top)
        layout.addSpacing(4)
        for label, bar in (
            (self.cpu_label, self.cpu_bar),
            (self.ram_label, self.ram_bar),
            (self.battery_label, self.battery_bar),
        ):
            layout.addWidget(label)
            layout.addWidget(bar)
        layout.addSpacing(4)
        layout.addWidget(self.activity)

    def update_from(self, device: dict, current: dict | None) -> None:
        online = device.get("connection_status") == "online"
        kind = device.get("device_type") or "unknown"
        self.icon.setText(DEVICE_ICONS.get(kind, "⬡"))

        details = [DEVICE_TYPE_TR.get(kind, "Cihaz")]
        if device.get("operating_system"):
            details.append(device["operating_system"])
        if device.get("cpu_cores"):
            details.append(f"{device['cpu_cores']} çekirdek")
        self.kind.setText(" • ".join(details))

        self.chip.setText("● Çevrimiçi" if online else "○ Çevrimdışı")
        self.chip.setObjectName("good" if online else "muted")
        repolish(self.chip)
        self.setProperty("state", "online" if online else "offline")
        repolish(self)

        usage = device.get("cpu_usage")
        if usage is None:
            self.cpu_label.setText("CPU  —")
            self.cpu_bar.setValue(0)
        else:
            self.cpu_label.setText(f"CPU  {usage:.0f} %")
            self.cpu_bar.setValue(int(usage))
            self.cpu_bar.setProperty("level", "bad" if usage >= 85 else "")
            repolish(self.cpu_bar)

        total, free = device.get("total_ram"), device.get("available_ram")
        if total and free is not None:
            used = max(0, total - free)
            self.ram_label.setText(
                f"RAM  {fmt_bytes(used)} / {fmt_bytes(total)}"
            )
            self.ram_bar.setValue(int(100 * used / total))
        else:
            self.ram_label.setText("RAM  —")
            self.ram_bar.setValue(0)

        battery = device.get("battery_level")
        has_battery = battery is not None
        self.battery_label.setVisible(has_battery)
        self.battery_bar.setVisible(has_battery)
        if has_battery:
            plug = "  ⚡ şarjda" if device.get("is_charging") else ""
            self.battery_label.setText(f"Pil  {battery:.0f} %{plug}")
            self.battery_bar.setValue(int(battery))
            self.battery_bar.setProperty(
                "level",
                "bad" if battery < 20 and not device.get("is_charging") else "good",
            )
            repolish(self.battery_bar)

        if current is not None:
            self.activity.setText(
                f"▶ Görev #{current['id']} · {current['task_type']}"
            )
        else:
            self.activity.setText("Boşta" if online else "Bağlantı yok")
