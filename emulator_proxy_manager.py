# -*- coding: utf-8 -*-
"""
emulator_proxy_manager.py
Ung dung GUI (PySide6) quan ly Android emulators + tich hop proxy + tu dong hoa.
Tinh nang:
  - Liet ke so luong may ao (AVD).
  - Tich hop proxy cho tung may ao (set/remove/test).
  - Supervisor tu phuc hoi: bridge luon chay + proxy tu dat lai sau reboot.
"""
import sys
import os
import json
import time
import threading

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTreeWidget, QTreeWidgetItem, QPushButton, QLabel, QTextEdit,
    QGroupBox, QLineEdit, QCheckBox, QSpinBox, QSplitter, QMessageBox,
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject

# Danh ba thu muc core
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from core.emulator import EmulatorManager
from core.proxy import ProxyManager
from core.bridge import BridgeManager, BridgePool
from core.autostart import Supervisor

# ---------- Cấu hình ----------
def _app_base():
    """Khi dong goi exe, BASE la thu muc cua exe; khi chay .py la thu muc script."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


BASE = _app_base()
CONFIG_PATH = os.path.join(BASE, "config.json")


def _resolve_bridge_script():
    """Uu tien http2socks_bridge.exe (dong goi) neu co, nguoc lai .py."""
    py_script = os.path.join(BASE, "http2socks_bridge.py")
    exe_script = os.path.join(BASE, "http2socks_bridge.exe")
    if os.path.exists(exe_script):
        return exe_script
    return py_script


def load_config():
    defaults = {
        "sdk_path": "C:/Users/Admin/AppData/Local/Android/Sdk",
        "bridge_script": _resolve_bridge_script(),
        "bridge_port": 8080,
        "default_proxy": "10.0.2.2:8080",
        "socks5": {"host": "14.224.225.153", "port": 51653,
                   "user": "yAEnTj", "password": "KMKoCt"},
        "supervisor_interval_sec": 10,
        "boot_timeout_sec": 180,
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            defaults.update(data)
        except Exception:
            pass
    # Khi dong goi exe, luon phan giai lai bridge_script sang file .exe cung thu muc
    if getattr(sys, "frozen", False):
        defaults["bridge_script"] = _resolve_bridge_script()
    return defaults


CFG = load_config()

# ---------- Bridge điều phối tín hiệu thread -> GUI ----------
class WorkerSignals(QObject):
    report = Signal(dict)       # supervisor report
    log = Signal(str)


# ---------- Worker supervisor chạy nền ----------
class SupervisorWorker:
    def __init__(self, supervisor, signals):
        self.supervisor = supervisor
        self.signals = signals

    def run(self):
        def cb(report):
            self.signals.report.emit(report)
        self.supervisor.callback = cb
        self.supervisor.start()
# ---------- Cửa sổ chính ----------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Android Emulator Proxy Manager")
        self.resize(1050, 720)

        # ---------- core ----------
        self.emu = EmulatorManager(CFG["sdk_path"])
        self.proxy = ProxyManager(CFG["sdk_path"], CFG["default_proxy"])
        self.bridge = BridgeManager(CFG["bridge_script"], CFG["bridge_port"])
        self.pool = BridgePool(CFG["bridge_script"], port_base=CFG.get("port_base", 8081))
        self.supervisor = Supervisor(
            self.bridge, self.emu, self.proxy, CFG["default_proxy"],
            interval=CFG["supervisor_interval_sec"], enabled=True,
            pool=self.pool, default_socks_port=CFG.get("bridge_port", 8080),
        )
        self.signals = WorkerSignals()
        self.signals.report.connect(self._on_report)
        self.signals.log.connect(lambda m: self._log(m))
        self.worker = SupervisorWorker(self.supervisor, self.signals)
        self._super_thread = None
        self.selected_avd = None
        self.avd_status = {}

        self._build_ui()
        self._log("Khoi dong. SDK: " + CFG["sdk_path"])
        self.refresh_emulators()

    # ========== Xây GUI ==========
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        # ==== Cột trái: danh sách máy ảo ====
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)

        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("<b>Danh sách máy ảo (AVD)</b>"))
        self.lbl_count = QLabel("")
        hdr.addWidget(self.lbl_count)
        hdr.addStretch(1)
        btn_refresh = QPushButton("Làm mới")
        btn_refresh.clicked.connect(self.refresh_emulators)
        hdr.addWidget(btn_refresh)
        lv.addLayout(hdr)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Tên AVD", "Trạng thái", "Serial", "Proxy"])
        self.tree.setColumnWidth(0, 150)
        self.tree.setColumnWidth(1, 110)
        self.tree.setColumnWidth(2, 120)
        self.tree.itemSelectionChanged.connect(self._on_select)
        lv.addWidget(self.tree, 1)

        # ==== Chi tiết thao tác ====
        det = QGroupBox("Thao tác máy ảo đang chọn")
        dv = QVBoxLayout(det)

        row1 = QHBoxLayout()
        self.btn_boot = QPushButton("Khởi động")
        self.btn_set = QPushButton("Gán proxy (IP riêng)")
        self.btn_remove = QPushButton("Gỡ proxy")
        self.btn_test = QPushButton("Kiểm tra IP qua proxy")
        self.btn_boot.clicked.connect(self._do_boot)
        self.btn_set.clicked.connect(self._do_set_proxy)
        self.btn_remove.clicked.connect(self._do_remove_proxy)
        self.btn_test.clicked.connect(self._do_test_proxy)
        for b in (self.btn_boot, self.btn_set, self.btn_remove, self.btn_test):
            row1.addWidget(b)
        dv.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Proxy SOCKS5 (host:port:user:pass):"))
        self.ed_proxy = QLineEdit(CFG["default_proxy"])
        self.ed_proxy.setPlaceholderText("vd: 14.224.225.153:51653:yAEnTj:KMKoCt")
        row2.addWidget(self.ed_proxy, 1)
        dv.addLayout(row2)
        self.lbl_selected = QLabel("Chưa chọn máy ảo")
        dv.addWidget(self.lbl_selected)

        lv.addWidget(det)
        splitter.addWidget(left)

        # ==== Cột phải: bridge + supervisor + log ====
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)

        # --- Bridge ---
        gb_bridge = QGroupBox("Bridge HTTP→SOCKS5")
        bv = QVBoxLayout(gb_bridge)
        br_row = QHBoxLayout()
        self.btn_bridge_start = QPushButton("Start bridge")
        self.btn_bridge_stop = QPushButton("Stop bridge")
        self.btn_bridge_status = QPushButton("Kiểm tra")
        self.btn_bridge_start.clicked.connect(self._bridge_start)
        self.btn_bridge_stop.clicked.connect(self._bridge_stop)
        self.btn_bridge_status.clicked.connect(self._bridge_status)
        for b in (self.btn_bridge_start, self.btn_bridge_stop, self.btn_bridge_status):
            br_row.addWidget(b)
        bv.addLayout(br_row)
        self.lbl_bridge = QLabel("Bridge: --")
        bv.addWidget(self.lbl_bridge)
        rv.addWidget(gb_bridge)

        # --- Supervisor ---
        gb_sup = QGroupBox("Tự động hóa (Supervisor)")
        sv = QVBoxLayout(gb_sup)
        s_row = QHBoxLayout()
        self.chk_supervisor = QCheckBox("Bật giám sát nền (tự phục hồi proxy)")
        self.chk_supervisor.setChecked(True)
        self.chk_supervisor.stateChanged.connect(self._toggle_supervisor)
        s_row.addWidget(self.chk_supervisor)
        s_row.addWidget(QLabel("Chu kỳ (s):"))
        self.spin_interval = QSpinBox()
        self.spin_interval.setRange(3, 300)
        self.spin_interval.setValue(CFG["supervisor_interval_sec"])
        self.spin_interval.valueChanged.connect(self._set_interval)
        s_row.addWidget(self.spin_interval)
        btn_run_once = QPushButton("Chạy ngay 1 vòng")
        btn_run_once.clicked.connect(self._supervise_now)
        s_row.addWidget(btn_run_once)
        sv.addLayout(s_row)
        self.lbl_supervisor = QLabel("Supervisor: chưa chạy")
        sv.addWidget(self.lbl_supervisor)
        rv.addWidget(gb_sup)

        # --- Log ---
        gb_log = QGroupBox("Nhật ký")
        lv2 = QVBoxLayout(gb_log)
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        lv2.addWidget(self.txt_log)
        rv.addWidget(gb_log, 1)

        splitter.addWidget(right)
        splitter.setSizes([520, 530])

    # ========== Tiện ích log ==========
    def _log(self, msg):
        ts = time.strftime("%H:%M:%S")
        self.txt_log.append(f"[{ts}] {msg}")
        sb = self.txt_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ========== Danh sách máy ảo ==========
    def refresh_emulators(self):
        try:
            self.avd_status = self.emu.avd_status()
        except Exception as e:
            self._log(f"Lỗi refresh: {e}")
            self.avd_status = {}
        self.tree.clear()
        for avd, info in self.avd_status.items():
            state = "đang chạy" if info["running"] else "tắt"
            serial = info["serial"] or ""
            proxy = ""
            if info["running"] and info["booted"]:
                try:
                    proxy = self.proxy.get_proxy(info["serial"])
                except Exception:
                    proxy = "lỗi đọc"
            elif info["running"]:
                proxy = "đang boot..."
            item = QTreeWidgetItem([avd, state, serial, proxy])
            if info["running"]:
                item.setForeground(1, Qt.GlobalColor.darkGreen)
            else:
                item.setForeground(1, Qt.GlobalColor.darkRed)
            self.tree.addTopLevelItem(item)
        self.lbl_count.setText(f"({len(self.avd_status)} máy ảo)")

    def _on_select(self):
        items = self.tree.selectedItems()
        if not items:
            self.selected_avd = None
            self.lbl_selected.setText("Chưa chọn máy ảo")
            return
        self.selected_avd = items[0].text(0)
        info = self.avd_status.get(self.selected_avd, {})
        running = info.get("running", False)
        self.lbl_selected.setText(
            f"Đã chọn: {self.selected_avd} | "
            f"{'ĐANG CHẠY' if running else 'ĐANG TẮT'} | "
            f"serial={info.get('serial') or '-'}")

    def _selected_serial(self):
        info = self.avd_status.get(self.selected_avd, {})
        return info.get("serial")

    # ========== Khởi động ==========
    def _do_boot(self):
        avd = self.selected_avd
        if not avd:
            QMessageBox.information(self, "Chú ý", "Hãy chọn một máy ảo.")
            return
        self._log(f"Đang khởi động AVD '{avd}' (không chờ boot)...")
        threading.Thread(target=self._boot_worker, args=(avd,), daemon=True).start()

    def _boot_worker(self, avd):
        try:
            self.emu.boot_avd(avd)
            self.signals.log.emit(f"Đã gửi lệnh khởi động {avd}. Chờ boot...")
            serial = self.emu.serial_to_booted(avd, timeout=CFG["boot_timeout_sec"], poll=3)
            if serial:
                self.signals.log.emit(f"{avd} đã boot xong (serial {serial}).")
                self.proxy.ensure_proxy(serial, CFG["default_proxy"])
                self.signals.log.emit(f"Đã đảm bảo proxy cho {avd}: {self.proxy.get_proxy(serial)}")
            else:
                self.signals.log.emit(f"Chưa thấy {avd} boot xong trong {CFG['boot_timeout_sec']}s.")
        except Exception as e:
            self.signals.log.emit(f"Lỗi boot {avd}: {e}")
        self.refresh_emulators()

    # ========== Proxy ==========
    def _do_set_proxy(self):
        serial = self._selected_serial()
        if not serial:
            QMessageBox.information(self, "Chú ý", "Máy ảo này chưa chạy hoặc chưa chọn.")
            return
        socks_str = self.ed_proxy.text().strip()
        if not socks_str:
            QMessageBox.information(self, "Chú ý",
                                    "Hãy nhập proxy dạng host:port:user:pass\nvd: 14.224.225.153:51653:yAEnTj:KMKoCt")
            return
        if not self.pool.socks_from_string(socks_str):
            QMessageBox.warning(self, "Sai định dạng",
                                "Chuỗi proxy phải có dạng host:port:user:pass")
            return
        # Chạy nền để không treo GUI khi khởi động bridge
        threading.Thread(target=self._set_proxy_worker, args=(serial, socks_str), daemon=True).start()

    def _set_proxy_worker(self, serial, socks_str):
        self.signals.log.emit(f"Đang chuẩn bị bridge + gán proxy riêng cho {self.selected_avd} ...")
        port, proxy_str = self.pool.assign_proxy(self.selected_avd, socks_str)
        if not proxy_str:
            self.signals.log.emit(f"❌ Không tạo được bridge cho proxy {socks_str}")
            return
        self.proxy.set_proxy(serial, proxy_str)
        self.signals.log.emit(
            f"✅ {self.selected_avd}: gán proxy {proxy_str} "
            f"(SOCKS5 {socks_str}, bridge port {port})")
        self.refresh_emulators()

    def _do_remove_proxy(self):
        serial = self._selected_serial()
        if not serial:
            QMessageBox.information(self, "Chú ý", "Máy ảo này chưa chạy hoặc chưa chọn.")
            return
        ok, msg = self.pool.remove_avd(self.selected_avd)
        self.proxy.remove_proxy(serial)
        self._log(f"Đã gỡ proxy cho {self.selected_avd} ({serial}) - {msg}")
        self.refresh_emulators()

    def _do_test_proxy(self):
        serial = self._selected_serial()
        if not serial:
            QMessageBox.information(self, "Chú ý", "Máy ảo này chưa chạy hoặc chưa chọn.")
            return
        # test qua port cua proxy da gan cho AVD nay
        port = self.pool.port_for_avd(self.selected_avd)
        if port is None:
            QMessageBox.information(self, "Chú ý",
                                    "Máy ảo này chưa được gán proxy qua pool. Hãy bấm 'Gán proxy (IP riêng)' trước.")
            return
        self._log(f"Kiểm tra proxy {self.selected_avd} (port {port}) ...")
        threading.Thread(target=self._test_worker, args=(serial, port), daemon=True).start()

    def _test_worker(self, serial, port):
        ok, res = self.proxy.test_proxy_port(serial, port)
        if ok:
            self.signals.log.emit(f"✅ {self.selected_avd} proxy hoạt động - IP ra ngoài: {res}")
        else:
            self.signals.log.emit(f"❌ {self.selected_avd} proxy lỗi: {res}")

    # ========== Bridge ==========
    def _bridge_start(self):
        ok, msg = self.bridge.start()
        self._log("Start bridge: " + msg)
        self._bridge_status()

    def _bridge_stop(self):
        msg = self.bridge.stop()
        self._log("Stop bridge: " + msg)
        self._bridge_status()

    def _bridge_status(self):
        ok, msg = self.bridge.status()
        color = "xanh" if ok else "đỏ"
        self.lbl_bridge.setText(f"Bridge: {msg} ({color})")
        self._log("Status bridge: " + msg)

    # ========== Supervisor ==========
    def _toggle_supervisor(self, state):
        enabled = (state == Qt.CheckState.Checked.value)
        self.supervisor.enabled = enabled
        self._log(f"Supervisor {'BẬT' if enabled else 'TẮT'}")
        if enabled and (not self._super_thread or not self._super_thread.is_alive()):
            self._start_supervisor_thread()

    def _start_supervisor_thread(self):
        self._super_thread = threading.Thread(target=self.worker.run, daemon=True)
        self._super_thread.start()
        self.lbl_supervisor.setText("Supervisor: ĐANG CHẠY (giám sát nền)")
        self._log("Supervisor đã bắt đầu chạy nền.")

    def _set_interval(self, val):
        self.supervisor.set_interval(val)
        self._log(f"Chu kỳ supervisor = {val}s")

    def _supervise_now(self):
        report = self.supervisor.supervise_once()
        self._on_report(report)

    def _on_report(self, report):
        br = report.get("bridge_running")
        if br is not None:
            self.lbl_bridge.setText(f"Bridge: {'ĐANG CHẠY' if br else 'TẮT'}")
        for kind, msg in report.get("actions", []):
            if kind == "bridge":
                self._log("[tự] Bridge: " + msg)
            elif kind == "proxy":
                self._log("[tự] Proxy: " + msg)
        changed = any(a[0] == "proxy" for a in report.get("actions", []))
        if changed:
            self.refresh_emulators()

    def closeEvent(self, event):
        self.supervisor.stop()
        event.accept()


# ========== Main ==========
def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    if win.chk_supervisor.isChecked():
        win._start_supervisor_thread()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

