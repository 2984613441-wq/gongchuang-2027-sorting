#!/usr/bin/env python3
"""智能分拣装置 - 完整数据链路监控 GUI

监控内容：
- 视觉检测结果（MaixCAM → 树莓派）
- 电控指令（树莓派 → STM32）
- 执行结果（STM32 → 树莓派）

用于验证数据链路是否打通、调试电控参数。
"""

import json
import socket
import sys
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


class SortingSystemMonitor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("智能分拣装置 - 数据链路监控")
        self.setGeometry(100, 100, 1200, 800)

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

        conn_layout.addWidget(QLabel("树莓派 IP:"))
        self.ip_input = QLineEdit("172.20.10.8")
        self.ip_input.setMaximumWidth(120)
        conn_layout.addWidget(self.ip_input)

        conn_layout.addWidget(QLabel("端口:"))
        self.port_input = QLineEdit("9002")
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

        # 标签页
        self.tabs = QTabWidget()

        # 标签页1：数据流监控
        self.data_flow_tab = QWidget()
        self.init_data_flow_tab()
        self.tabs.addTab(self.data_flow_tab, "数据流监控")

        # 标签页2：视觉检测
        self.vision_tab = QWidget()
        self.init_vision_tab()
        self.tabs.addTab(self.vision_tab, "视觉检测")

        # 标签页3：电控指令
        self.control_tab = QWidget()
        self.init_control_tab()
        self.tabs.addTab(self.control_tab, "电控指令")

        # 标签页4：执行结果
        self.result_tab = QWidget()
        self.init_result_tab()
        self.tabs.addTab(self.result_tab, "执行结果")

        main_layout.addWidget(self.tabs)

    def init_data_flow_tab(self):
        """数据流概览"""
        layout = QVBoxLayout(self.data_flow_tab)

        # 更新时间
        time_group = QGroupBox("实时状态")
        time_layout = QFormLayout()
        self.last_update_label = QLabel("--")
        time_layout.addRow("最后更新:", self.last_update_label)
        time_group.setLayout(time_layout)
        layout.addWidget(time_group)

        # 数据流状态
        flow_group = QGroupBox("数据链路状态")
        flow_layout = QVBoxLayout()

        # 视觉 → 树莓派
        vision_layout = QHBoxLayout()
        vision_layout.addWidget(QLabel("📷 视觉检测 →"))
        self.vision_status = QLabel("等待数据...")
        self.vision_status.setStyleSheet("color: gray;")
        vision_layout.addWidget(self.vision_status)
        vision_layout.addStretch()
        flow_layout.addLayout(vision_layout)

        # 树莓派 → STM32
        task_layout = QHBoxLayout()
        task_layout.addWidget(QLabel("📤 电控指令 →"))
        self.task_status = QLabel("等待数据...")
        self.task_status.setStyleSheet("color: gray;")
        task_layout.addWidget(self.task_status)
        task_layout.addStretch()
        flow_layout.addLayout(task_layout)

        # STM32 → 树莓派
        result_layout = QHBoxLayout()
        result_layout.addWidget(QLabel("✅ 执行结果 ←"))
        self.result_status = QLabel("等待数据...")
        self.result_status.setStyleSheet("color: gray;")
        result_layout.addWidget(self.result_status)
        result_layout.addStretch()
        flow_layout.addLayout(result_layout)

        flow_group.setLayout(flow_layout)
        layout.addWidget(flow_group)

        layout.addStretch()

    def init_vision_tab(self):
        """视觉检测数据"""
        layout = QVBoxLayout(self.vision_tab)

        info_group = QGroupBox("视觉检测信息")
        info_layout = QFormLayout()
        self.vision_task_id = QLabel("--")
        self.vision_count = QLabel("0")
        info_layout.addRow("Task ID:", self.vision_task_id)
        info_layout.addRow("检测数量:", self.vision_count)
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)

        layout.addWidget(QLabel("检测目标:"))
        self.vision_table = QTableWidget()
        self.vision_table.setColumnCount(3)
        self.vision_table.setHorizontalHeaderLabels(["序号", "类别ID", "盒子ID"])
        layout.addWidget(self.vision_table)

    def init_control_tab(self):
        """电控指令数据"""
        layout = QVBoxLayout(self.control_tab)

        info_group = QGroupBox("当前指令")
        info_layout = QFormLayout()
        self.ctrl_round_id = QLabel("--")
        self.ctrl_task_id = QLabel("--")
        self.ctrl_frame_seq = QLabel("--")
        self.ctrl_target_seq = QLabel("--")
        self.ctrl_class_id = QLabel("--")
        self.ctrl_x_pos = QLabel("--")
        self.ctrl_y_pos = QLabel("--")

        info_layout.addRow("轮次ID:", self.ctrl_round_id)
        info_layout.addRow("任务ID:", self.ctrl_task_id)
        info_layout.addRow("帧序号:", self.ctrl_frame_seq)
        info_layout.addRow("目标序号:", self.ctrl_target_seq)
        info_layout.addRow("类别ID:", self.ctrl_class_id)
        info_layout.addRow("X坐标 (0.1mm):", self.ctrl_x_pos)
        info_layout.addRow("Y坐标 (0.1mm):", self.ctrl_y_pos)

        info_group.setLayout(info_layout)
        layout.addWidget(info_group)
        layout.addStretch()

    def init_result_tab(self):
        """执行结果数据"""
        layout = QVBoxLayout(self.result_tab)

        info_group = QGroupBox("最新结果")
        info_layout = QFormLayout()
        self.result_target_seq = QLabel("--")
        self.result_code = QLabel("--")
        self.result_basis = QLabel("--")
        self.result_success = QLabel("--")

        info_layout.addRow("目标序号:", self.result_target_seq)
        info_layout.addRow("结果代码:", self.result_code)
        info_layout.addRow("依据:", self.result_basis)
        info_layout.addRow("是否成功:", self.result_success)

        info_group.setLayout(info_layout)
        layout.addWidget(info_group)
        layout.addStretch()

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

            # 启动接收线程
            self.recv_thread = RecvThread(self.sock)
            self.recv_thread.data_received.connect(self.on_data_received)
            self.recv_thread.connection_lost.connect(self.on_connection_lost)
            self.recv_thread.start()

            print(f"[INFO] 已连接到 {host}:{port}")

        except Exception as e:
            QMessageBox.critical(self, "连接失败", f"无法连接到树莓派:\n{e}")
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
        self.reconnect_timer.stop()

    def on_connection_lost(self):
        """连接丢失，尝试自动重连"""
        self.disconnect()
        QMessageBox.warning(self, "连接断开", "与树莓派的连接已断开\n将每5秒尝试重连...")
        self.reconnect_timer.start(5000)

    def try_reconnect(self):
        """自动重连"""
        print("[INFO] 尝试重连...")
        self.connect()
        if self.connected:
            self.reconnect_timer.stop()
            QMessageBox.information(self, "重连成功", "已重新连接到树莓派")

    def on_data_received(self, data):
        """更新UI显示"""
        # 更新时间
        self.last_update_label.setText(datetime.now().strftime("%H:%M:%S"))

        # 更新视觉数据
        vision = data.get('vision')
        if vision:
            self.vision_task_id.setText(str(vision.get('task_id', '--')))
            targets = vision.get('targets', [])
            self.vision_count.setText(str(len(targets)))

            self.vision_table.setRowCount(len(targets))
            for i, target in enumerate(targets):
                self.vision_table.setItem(i, 0, QTableWidgetItem(str(target.get('target_seq', ''))))
                self.vision_table.setItem(i, 1, QTableWidgetItem(str(target.get('class_id', ''))))
                self.vision_table.setItem(i, 2, QTableWidgetItem(str(target.get('box_id', ''))))

            self.vision_status.setText(f"{len(targets)}个目标")
            self.vision_status.setStyleSheet("color: green; font-weight: bold;")

        # 更新电控指令
        item_task = data.get('item_task')
        if item_task:
            self.ctrl_round_id.setText(item_task.get('round_id', '--'))
            self.ctrl_task_id.setText(str(item_task.get('task_id', '--')))
            self.ctrl_frame_seq.setText(str(item_task.get('frame_seq', '--')))
            self.ctrl_target_seq.setText(str(item_task.get('target_seq', '--')))
            self.ctrl_class_id.setText(str(item_task.get('class_id', '--')))
            self.ctrl_x_pos.setText(str(item_task.get('x_position', '--')))
            self.ctrl_y_pos.setText(str(item_task.get('y_position', '--')))

            self.task_status.setText(f"目标#{item_task.get('target_seq', '?')}")
            self.task_status.setStyleSheet("color: blue; font-weight: bold;")

        # 更新执行结果
        item_result = data.get('item_result')
        if item_result:
            self.result_target_seq.setText(str(item_result.get('target_seq', '--')))
            self.result_code.setText(f"0x{item_result.get('result_code', 0):02X}")
            self.result_basis.setText(f"0x{item_result.get('basis', 0):02X}")

            success = item_result.get('success', False)
            self.result_success.setText("✅ 成功" if success else "❌ 失败")

            if success:
                self.result_status.setText("✅ 成功")
                self.result_status.setStyleSheet("color: green; font-weight: bold;")
            else:
                self.result_status.setText("❌ 失败")
                self.result_status.setStyleSheet("color: red; font-weight: bold;")

    def closeEvent(self, event):
        """窗口关闭时清理资源"""
        self.disconnect()
        event.accept()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = SortingSystemMonitor()
    window.show()
    sys.exit(app.exec_())
