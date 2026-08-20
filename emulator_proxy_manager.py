from __future__ import annotations

import sys
import threading
import time

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.logging_setup import configure_logging
from core.models import SocksProxy
from core.runtime import build_runtime


class UiSignals(QObject):
    log = Signal(str)
    refresh = Signal()
    refresh_data = Signal(object)
    report = Signal(dict)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.signals = UiSignals()
        self.runtime = build_runtime(callback=lambda report: self.signals.report.emit(report))
        self.logger = configure_logging(self.runtime.config.log_dir)
        self.selected_avd: str | None = None
        self.avd_status: dict[str, dict] = {}
        self._bridge_health: dict[str, dict] = {}
        self._refreshing = False

        self.signals.log.connect(self._log)
        self.signals.refresh.connect(self.refresh_emulators)
        self.signals.refresh_data.connect(self._apply_refresh)
        self.signals.report.connect(self._on_report)

        self.setWindowTitle("Android Emulator Proxy Manager")
        self.resize(1120, 760)
        self._build_ui()
        self._log(f"SDK: {self.runtime.config.sdk_path or '(not configured)'}")
        self.refresh_emulators()
        self.runtime.supervisor.start()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, 1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        header = QHBoxLayout()
        header.addWidget(QLabel("<b>Android Virtual Devices</b>"))
        self.count_label = QLabel("")
        header.addWidget(self.count_label)
        header.addStretch(1)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_emulators)
        header.addWidget(refresh)
        left_layout.addLayout(header)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["AVD", "State", "Serial", "Android proxy", "Proxy ID"])
        self.tree.itemSelectionChanged.connect(self._on_select)
        left_layout.addWidget(self.tree, 1)

        actions = QGroupBox("Selected AVD")
        actions_layout = QVBoxLayout(actions)
        buttons = QHBoxLayout()
        self.boot_button = QPushButton("Boot")
        self.assign_button = QPushButton("Assign proxy")
        self.remove_button = QPushButton("Remove proxy")
        self.test_button = QPushButton("Test exit IP")
        self.boot_button.clicked.connect(self._boot_selected)
        self.assign_button.clicked.connect(self._assign_selected)
        self.remove_button.clicked.connect(self._remove_selected)
        self.test_button.clicked.connect(self._test_selected)
        for button in (self.boot_button, self.assign_button, self.remove_button, self.test_button):
            buttons.addWidget(button)
        actions_layout.addLayout(buttons)

        proxy_row = QHBoxLayout()
        proxy_row.addWidget(QLabel("SOCKS5:"))
        self.proxy_input = QLineEdit()
        self.proxy_input.setPlaceholderText("socks5://username:password@host:port")
        self.proxy_input.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
        proxy_row.addWidget(self.proxy_input, 1)
        actions_layout.addLayout(proxy_row)
        self.selection_label = QLabel("No AVD selected")
        actions_layout.addWidget(self.selection_label)
        left_layout.addWidget(actions)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        supervisor_group = QGroupBox("Supervisor")
        supervisor_layout = QVBoxLayout(supervisor_group)
        supervisor_row = QHBoxLayout()
        self.supervisor_checkbox = QCheckBox("Enable automatic recovery")
        self.supervisor_checkbox.setChecked(True)
        self.supervisor_checkbox.stateChanged.connect(self._toggle_supervisor)
        supervisor_row.addWidget(self.supervisor_checkbox)
        supervisor_row.addWidget(QLabel("Interval (s):"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(3, 300)
        self.interval_spin.setValue(self.runtime.config.supervisor_interval_sec)
        self.interval_spin.valueChanged.connect(self.runtime.supervisor.set_interval)
        supervisor_row.addWidget(self.interval_spin)
        run_once = QPushButton("Run now")
        run_once.clicked.connect(self._supervise_once)
        supervisor_row.addWidget(run_once)
        supervisor_layout.addLayout(supervisor_row)
        self.supervisor_label = QLabel("Supervisor running")
        supervisor_layout.addWidget(self.supervisor_label)
        right_layout.addWidget(supervisor_group)

        bridge_group = QGroupBox("Bridge registry")
        bridge_layout = QVBoxLayout(bridge_group)
        self.bridge_text = QTextEdit()
        self.bridge_text.setReadOnly(True)
        self.bridge_text.setMaximumHeight(180)
        bridge_layout.addWidget(self.bridge_text)
        right_layout.addWidget(bridge_group)

        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout(log_group)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        right_layout.addWidget(log_group, 1)
        splitter.addWidget(right)
        splitter.setSizes([650, 470])

    def _run_worker(self, target, *args) -> None:
        def wrapper():
            try:
                target(*args)
            except Exception as exc:
                self.signals.log.emit(f"ERROR: {exc}")
            finally:
                self.signals.refresh.emit()

        threading.Thread(target=wrapper, daemon=True).start()

    def _log(self, message: str) -> None:
        text = f"[{time.strftime('%H:%M:%S')}] {message}"
        self.log_text.append(text)
        self.logger.info(message)
        scroll = self.log_text.verticalScrollBar()
        scroll.setValue(scroll.maximum())

    def refresh_emulators(self) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        threading.Thread(target=self._collect_refresh, daemon=True).start()

    def _collect_refresh(self) -> None:
        try:
            status = self.runtime.emulators.avd_status()
            assignments = self.runtime.state.all_assignments()
            current: dict[str, str] = {}
            for avd, info in status.items():
                if info.get("running") and info.get("booted") and info.get("serial"):
                    result = self.runtime.proxy.get_proxy(info["serial"])
                    current[avd] = result.proxy if result.success else "ADB error"
                elif info.get("running"):
                    current[avd] = "booting"
                else:
                    current[avd] = ""
            health = self.runtime.registry.health()
            self.signals.refresh_data.emit(
                {"status": status, "assignments": assignments, "current": current, "health": health}
            )
        except Exception as exc:
            self.signals.refresh_data.emit({"error": str(exc)})

    def _apply_refresh(self, payload: dict) -> None:
        self._refreshing = False
        if payload.get("error"):
            self._log(f"Refresh failed: {payload['error']}")
            return
        self.avd_status = payload["status"]
        assignments = payload["assignments"]
        current = payload["current"]
        self._bridge_health = payload["health"]
        self.tree.clear()
        for avd, info in self.avd_status.items():
            assignment = assignments.get(avd)
            proxy_id = assignment.proxy_id if assignment else ""
            state = "running" if info.get("running") else "stopped"
            item = QTreeWidgetItem(
                [avd, state, info.get("serial") or "", current.get(avd, ""), proxy_id]
            )
            item.setForeground(1, QColor("darkgreen" if info.get("running") else "darkred"))
            self.tree.addTopLevelItem(item)
        self.count_label.setText(f"({len(self.avd_status)})")
        self._render_bridge_health()

    def _render_bridge_health(self) -> None:
        lines: list[str] = []
        for proxy_id, item in self._bridge_health.items():
            status = "healthy" if item["healthy"] else "down"
            lines.append(f"{proxy_id} | port {item['port']} | {status}")
        self.bridge_text.setPlainText("\n".join(lines) if lines else "No active assignments")

    def _on_select(self) -> None:
        items = self.tree.selectedItems()
        if not items:
            self.selected_avd = None
            self.selection_label.setText("No AVD selected")
            return
        self.selected_avd = items[0].text(0)
        info = self.avd_status.get(self.selected_avd, {})
        self.selection_label.setText(
            f"{self.selected_avd} | serial={info.get('serial') or '-'} | "
            f"{'running' if info.get('running') else 'stopped'}"
        )

    def _snapshot(self, require_running: bool = False) -> tuple[str, str | None] | None:
        avd = self.selected_avd
        if not avd:
            QMessageBox.information(self, "Select AVD", "Select an Android Virtual Device first.")
            return None
        serial = self.avd_status.get(avd, {}).get("serial")
        if require_running and not serial:
            QMessageBox.information(self, "AVD not running", "Boot the selected AVD first.")
            return None
        return avd, serial

    def _boot_selected(self) -> None:
        snapshot = self._snapshot()
        if not snapshot:
            return
        avd, _ = snapshot
        self._run_worker(self._boot_worker, avd)

    def _boot_worker(self, avd: str) -> None:
        result = self.runtime.emulators.boot_avd(avd)
        if not result.success:
            self.signals.log.emit(f"{avd}: boot failed: {result.error}")
            return
        self.signals.log.emit(result.stdout)
        serial = self.runtime.emulators.wait_until_booted(
            avd, timeout=self.runtime.config.boot_timeout_sec, poll=3
        )
        if not serial:
            self.signals.log.emit(f"{avd}: boot timeout")
            return
        expected = self.runtime.registry.proxy_for_avd(avd)
        if expected:
            self.runtime.registry.ensure_all()
            restored = self.runtime.proxy.ensure_proxy(serial, expected)
            if not restored.success:
                self.signals.log.emit(f"{avd}: proxy restore failed: {restored.error}")
                return
        self.signals.log.emit(f"{avd}: ready on {serial}")

    def _assign_selected(self) -> None:
        snapshot = self._snapshot(require_running=True)
        if not snapshot:
            return
        raw = self.proxy_input.text().strip()
        try:
            parsed = SocksProxy.parse(raw)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid proxy", str(exc))
            return
        avd, serial = snapshot
        self._run_worker(self._assign_worker, avd, str(serial), parsed)

    def _assign_worker(self, avd: str, serial: str, parsed: SocksProxy) -> None:
        proxy_id = self.runtime.proxies.upsert(parsed)
        ok, message, port = self.runtime.registry.assign(avd, proxy_id)
        if not ok or port is None:
            self.signals.log.emit(f"{avd}: bridge failed: {message}")
            return
        expected = self.runtime.registry.proxy_for_avd(avd)
        result = self.runtime.proxy.set_proxy(serial, expected)
        if not result.success:
            self.signals.log.emit(f"{avd}: ADB proxy failed: {result.error}")
            return
        self.signals.log.emit(
            f"{avd}: assigned {parsed.redacted()} via {expected} ({proxy_id})"
        )

    def _remove_selected(self) -> None:
        snapshot = self._snapshot()
        if not snapshot:
            return
        avd, serial = snapshot
        self._run_worker(self._remove_worker, avd, serial)

    def _remove_worker(self, avd: str, serial: str | None) -> None:
        if serial:
            result = self.runtime.proxy.remove_proxy(serial)
            if not result.success:
                self.signals.log.emit(f"{avd}: Android proxy clear failed: {result.error}")
        ok, message = self.runtime.registry.remove(avd)
        self.signals.log.emit(message if ok else f"{avd}: {message}")

    def _test_selected(self) -> None:
        snapshot = self._snapshot()
        if not snapshot:
            return
        avd, _ = snapshot
        port = self.runtime.registry.port_for_avd(avd)
        if port is None:
            QMessageBox.information(self, "No proxy", "Assign a proxy to this AVD first.")
            return
        self._run_worker(self._test_worker, avd, port)

    def _test_worker(self, avd: str, port: int) -> None:
        self.runtime.registry.ensure_all()
        ok, detail = self.runtime.proxy.test_proxy_port(port, self.runtime.config.proxy_test_url)
        if ok:
            self.signals.log.emit(f"{avd}: bridge exit IP = {detail}")
        else:
            self.signals.log.emit(f"{avd}: bridge test failed: {detail}")

    def _toggle_supervisor(self, state: int) -> None:
        enabled = state == Qt.CheckState.Checked.value
        self.runtime.supervisor.enabled = enabled
        self.supervisor_label.setText("Supervisor running" if enabled else "Supervisor paused")
        self._log(f"Supervisor {'enabled' if enabled else 'paused'}")

    def _supervise_once(self) -> None:
        self._run_worker(self._supervise_worker)

    def _supervise_worker(self) -> None:
        report = self.runtime.supervisor.supervise_once()
        self.signals.report.emit(report)

    def _on_report(self, report: dict) -> None:
        for kind, message in report.get("actions", []):
            self._log(f"[{kind}] {message}")
        if "bridges" in report:
            self._bridge_health = report["bridges"]
            self._render_bridge_health()
        if report.get("actions"):
            self.refresh_emulators()

    def closeEvent(self, event) -> None:
        self.runtime.supervisor.stop()
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
