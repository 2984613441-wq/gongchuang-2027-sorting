#!/usr/bin/env python3
"""MaixCAM 监控 GUI —— ✅ 可用（2026-09-15 起）

连接 MaixCAM 的 9001 监控端口（默认 172.20.10.2:9001），显示**原始**检测结果：
  - 类别ID / 类别名 / 置信度 / 中心像素坐标
  - FPS、检测数量、最后更新时间
并支持：
  - 发送 UPDATE_PARAMS 热更新 CONF_TH / IOU_TH（与树莓派通道共用同一个 params）
  - 发送 SAVE_SCREENSHOT 让 MaixCAM 保存当前帧（带检测框）到 /root/screenshots/

【依赖的 MaixCAM 侧实现】
`视觉/src/maixcam_deploy/main.py` 的 `MonitorServer` 类（2026-09-15 新增）。
默认已启用（`ENABLE_MONITOR=1`，`MONITOR_PORT=9001`）。可关：
    ENABLE_MONITOR=0 python main.py
该服务是**只读旁路**：网络收发全在守护线程，检测主循环只做一次赋值，
客户端再慢也不影响检测；监控起不来也不会影响生产通道（8765）。

【该用哪个】
  - 想看 MaixCAM **原始**检测（置信度/像素坐标）+ 热调参 + 截图 → 本程序（9001）
  - 想看**全链路**（视觉 → 树莓派 → STM32 指令 → 执行结果） → `monitor_gui_v2.py`（9002）

端口总表与用法见 `工具/README.md`。
"""

import json
import socket
import sys
import time
from datetime import datetime

from PyQt5.QtCore import QThread, QTimer, pyqtSignal, Qt
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGroupBox, QFormLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QMessageBox, QLineEdit, QTabWidget
)


class RecvThread(QThread):
    """接收监控数据的后台线程"""
    data_received = pyqtSignal(dict)
    connection_lost = pyqtSignal()

    def __init__(self, sock):
        super().__init__()
        self.sock = sock
        self.running = True

    def run(self):
        buffer = b''
        try:
            while self.running:
                chunk = self.sock.recv(4096)
                if not chunk:
                    self.connection_lost.emit()
                    break

                buffer += chunk
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    try:
                        data = json.loads(line.decode())
                        self.data_received.emit(data)
                    except Exception as e:
                        print(f"[ERROR] JSON解析失败: {e}")
        except Exception as e:
            print(f"[ERROR] 接收线程异常: {e}")
            self.connection_lost.emit()

    def stop(self):
        self.running = False


class MaixCAMMonitor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MaixCAM 实时监控")
        self.setGeometry(100, 100, 1000, 700)

        self.sock = None
        self.recv_thread = None
        self.connected = False
        self.reconnect_timer = QTimer()
        self.reconnect_timer.timeout.connect(self.try_reconnect)

        self.init_ui()

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # 连接区域
        conn_group = QGroupBox("连接配置")
        conn_layout = QHBoxLayout()

        conn_layout.addWidget(QLabel("MaixCAM IP:"))
        self.ip_input = QLineEdit("172.20.10.2")
        self.ip_input.setMaximumWidth(120)
        conn_layout.addWidget(self.ip_input)

        conn_layout.addWidget(QLabel("端口:"))
        self.port_input = QLineEdit("9001")
        self.port_input.setMaximumWidth(60)
        conn_layout.addWidget(self.port_input)

        self.status_label = QLabel("未连接")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        conn_layout.addWidget(self.status_label)

        self.connect_btn = QPushButton("连接")
        self.connect_btn.clicked.connect(self.toggle_connection)
        conn_layout.addWidget(self.connect_btn)

        conn_layout.addStretch()
        conn_group.setLayout(conn_layout)
        main_layout.addWidget(conn_group)

        # 参数调整区域
        param_group = QGroupBox("参数调整")
        param_layout = QFormLayout()

        # 置信度阈值
        conf_layout = QHBoxLayout()
        self.conf_slider = QSlider(Qt.Horizontal)
        self.conf_slider.setRange(10, 95)
        # 默认值 = 2026-09-15 冻结的 0.5（勿改回 0.3：0.3 已作废）
        self.conf_slider.setValue(50)
        self.conf_slider.valueChanged.connect(self.on_conf_changed)
        self.conf_label = QLabel("0.50")
        conf_layout.addWidget(self.conf_slider)
        conf_layout.addWidget(self.conf_label)
        param_layout.addRow("置信度阈值:", conf_layout)

        # IOU阈值
        iou_layout = QHBoxLayout()
        self.iou_slider = QSlider(Qt.Horizontal)
        self.iou_slider.setRange(10, 95)
        self.iou_slider.setValue(45)
        self.iou_slider.valueChanged.connect(self.on_iou_changed)
        self.iou_label = QLabel("0.45")
        iou_layout.addWidget(self.iou_slider)
        iou_layout.addWidget(self.iou_label)
        param_layout.addRow("IOU阈值:", iou_layout)

        # 应用按钮
        self.apply_btn = QPushButton("应用参数")
        self.apply_btn.clicked.connect(self.apply_params)
        self.apply_btn.setEnabled(False)
        param_layout.addRow("", self.apply_btn)

        param_group.setLayout(param_layout)
        main_layout.addWidget(param_group)

        # 实时数据区域
        data_group = QGroupBox("实时数据")
        data_layout = QHBoxLayout()

        info_layout = QFormLayout()
        self.fps_label = QLabel("0.0")
        self.det_count_label = QLabel("0")
        self.last_update_label = QLabel("--")

        info_layout.addRow("FPS:", self.fps_label)
        info_layout.addRow("检测数量:", self.det_count_label)
        info_layout.addRow("最后更新:", self.last_update_label)

        data_layout.addLayout(info_layout)

        # 截图按钮
        self.screenshot_btn = QPushButton("保存截图到MaixCAM")
        self.screenshot_btn.clicked.connect(self.save_screenshot)
        self.screenshot_btn.setEnabled(False)
        data_layout.addWidget(self.screenshot_btn)

        data_layout.addStretch()
        data_group.setLayout(data_layout)
        main_layout.addWidget(data_group)

        # 检测结果表格
        main_layout.addWidget(QLabel("检测结果:"))
        self.det_table = QTableWidget()
        self.det_table.setColumnCount(5)
        self.det_table.setHorizontalHeaderLabels(["类别ID", "类别名", "置信度", "中心X", "中心Y"])
        self.det_table.setColumnWidth(0, 60)
        self.det_table.setColumnWidth(1, 100)
        self.det_table.setColumnWidth(2, 80)
        self.det_table.setColumnWidth(3, 80)
        self.det_table.setColumnWidth(4, 80)
        main_layout.addWidget(self.det_table)

    def toggle_connection(self):
        if self.connected:
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        host = self.ip_input.text()
        port = int(self.port_input.text())

        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5.0)
            self.sock.connect((host, port))
            self.sock.settimeout(None)

            self.connected = True
            self.status_label.setText("已连接")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
            self.connect_btn.setText("断开")
            self.apply_btn.setEnabled(True)
            self.screenshot_btn.setEnabled(True)

            # 启动接收线程
            self.recv_thread = RecvThread(self.sock)
            self.recv_thread.data_received.connect(self.on_data_received)
            self.recv_thread.connection_lost.connect(self.on_connection_lost)
            self.recv_thread.start()

            print(f"[INFO] 已连接到 {host}:{port}")

        except Exception as e:
            QMessageBox.critical(self, "连接失败", f"无法连接到MaixCAM:\n{e}")
            self.disconnect()

    def disconnect(self):
        if self.recv_thread:
            self.recv_thread.stop()
            self.recv_thread.wait(1000)
            self.recv_thread = None

        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None

        self.connected = False
        self.status_label.setText("未连接")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        self.connect_btn.setText("连接")
        self.apply_btn.setEnabled(False)
        self.screenshot_btn.setEnabled(False)
        self.reconnect_timer.stop()

    def on_connection_lost(self):
        """连接丢失，尝试自动重连"""
        self.disconnect()
        QMessageBox.warning(self, "连接断开", "与MaixCAM的连接已断开\n将每5秒尝试重连...")
        self.reconnect_timer.start(5000)

    def try_reconnect(self):
        """自动重连"""
        print("[INFO] 尝试重连...")
        self.connect()
        if self.connected:
            self.reconnect_timer.stop()
            QMessageBox.information(self, "重连成功", "已重新连接到MaixCAM")

    def on_conf_changed(self, value):
        self.conf_label.setText(f"{value/100:.2f}")

    def on_iou_changed(self, value):
        self.iou_label.setText(f"{value/100:.2f}")

    def apply_params(self):
        """发送参数更新命令"""
        if not self.connected:
            QMessageBox.warning(self, "未连接", "请先连接MaixCAM")
            return

        cmd = {
            'type': 'UPDATE_PARAMS',
            'conf_th': self.conf_slider.value() / 100,
            'iou_th': self.iou_slider.value() / 100
        }

        try:
            self.sock.sendall(json.dumps(cmd).encode() + b'\n')
            QMessageBox.information(self, "成功", "参数已发送到MaixCAM")
        except Exception as e:
            QMessageBox.critical(self, "发送失败", f"参数发送失败:\n{e}")

    def save_screenshot(self):
        """发送截图命令"""
        if not self.connected:
            QMessageBox.warning(self, "未连接", "请先连接MaixCAM")
            return

        cmd = {'type': 'SAVE_SCREENSHOT'}

        try:
            self.sock.sendall(json.dumps(cmd).encode() + b'\n')
            QMessageBox.information(self, "成功", f"截图命令已发送\n图像将保存到MaixCAM的/root/screenshots/目录")
        except Exception as e:
            QMessageBox.critical(self, "发送失败", f"截图命令发送失败:\n{e}")

    def on_data_received(self, data):
        """更新UI显示"""
        # 更新FPS
        self.fps_label.setText(f"{data.get('fps', 0.0):.1f}")

        # 更新检测数量
        detections = data.get('detections', [])
        self.det_count_label.setText(str(len(detections)))

        # 更新时间
        self.last_update_label.setText(datetime.now().strftime("%H:%M:%S"))

        # 更新表格
        self.det_table.setRowCount(len(detections))
        for i, det in enumerate(detections):
            self.det_table.setItem(i, 0, QTableWidgetItem(str(det['class_id'])))
            self.det_table.setItem(i, 1, QTableWidgetItem(det['class_name']))
            self.det_table.setItem(i, 2, QTableWidgetItem(f"{det['confidence']:.2f}"))
            self.det_table.setItem(i, 3, QTableWidgetItem(str(det['center'][0])))
            self.det_table.setItem(i, 4, QTableWidgetItem(str(det['center'][1])))

    def closeEvent(self, event):
        """窗口关闭时清理资源"""
        self.disconnect()
        event.accept()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MaixCAMMonitor()
    window.show()
    sys.exit(app.exec_())
