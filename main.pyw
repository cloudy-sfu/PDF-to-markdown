import logging

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, QTimer
from PyQt6.QtGui import QColor, QBrush
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QFileDialog,
    QTextEdit, QHeaderView, QAbstractItemView
)

from chandra.predict import predict_pdf, predict_image


class LogStream(QObject):
    new_log = pyqtSignal(str)

    def write(self, text):
        if text.strip():
            self.new_log.emit(text.strip())

    def flush(self):
        pass


class LogHandler(logging.Handler):
    def __init__(self, stream):
        super().__init__()
        self.stream = stream

    def emit(self, record):
        msg = self.format(record)
        self.stream.write(msg)


class Worker(QThread):
    task_started = pyqtSignal(int)
    task_finished = pyqtSignal(int, bool, str)
    all_finished = pyqtSignal()

    def __init__(self, tasks, parent=None):
        super().__init__(parent)
        self.tasks = tasks
        self.running = True

    def run(self):
        for i, task in enumerate(self.tasks):
            if not self.running:
                break

            row = task['row']
            input_file = task['input']
            output_dir = task['output']
            page_range = task['pages']
            layout = task['layout']

            self.task_started.emit(row)
            try:
                if input_file.lower().endswith('.pdf'):
                    predict_pdf(input_file, output_dir, page_range, layout)
                else:
                    predict_image(input_file, output_dir, layout)
                self.task_finished.emit(row, True, "Completed")
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.task_finished.emit(row, False, str(e))

        self.all_finished.emit()

    def stop(self):
        self.running = False


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF to markdown")
        self.resize(1024, 600)

        # Setup Logging
        self.log_stream = LogStream()
        self.log_stream.new_log.connect(self.append_log)

        logging.getLogger().setLevel(logging.INFO)
        formatter = logging.Formatter("[%(levelname)s] %(message)s")
        handler = LogHandler(self.log_stream)
        handler.setFormatter(formatter)
        logging.getLogger().addHandler(handler)

        central_widget = QWidget()
        layout = QVBoxLayout(central_widget)

        controls_layout = QHBoxLayout()

        self.tasks_controls = QWidget()
        tasks_layout = QHBoxLayout(self.tasks_controls)
        tasks_layout.setContentsMargins(0, 0, 0, 0)

        self.btn_add = QPushButton("Add")
        self.btn_add.clicked.connect(self.add_tasks)
        self.btn_delete = QPushButton("Delete")
        self.btn_delete.clicked.connect(self.delete_tasks)
        self.btn_start = QPushButton("Start all")
        self.btn_start.clicked.connect(self.start_processing)

        tasks_layout.addWidget(self.btn_add)
        tasks_layout.addWidget(self.btn_delete)
        tasks_layout.addWidget(self.btn_start)

        self.worker_controls = QWidget()
        worker_layout = QHBoxLayout(self.worker_controls)
        worker_layout.setContentsMargins(0, 0, 0, 0)

        self.btn_skip = QPushButton("Skip")
        self.btn_skip.clicked.connect(self.skip_current)
        self.btn_stop = QPushButton("Stop all")
        self.btn_stop.clicked.connect(self.stop_all)

        worker_layout.addWidget(self.btn_skip)
        worker_layout.addWidget(self.btn_stop)
        self.worker_controls.setEnabled(False)

        controls_layout.addWidget(self.tasks_controls)
        controls_layout.addWidget(self.worker_controls)
        controls_layout.addStretch()
        layout.addLayout(controls_layout)

        # Table
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Input file", "Output directory", "Page ranges", "Layout",
             "Status" + " " * 8])

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setCascadingSectionResizes(True)

        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.cellDoubleClicked.connect(self.on_cell_double_clicked)
        # Apply layout checkbox when clicking in layout column
        self.table.cellClicked.connect(self.on_cell_clicked)

        layout.addWidget(self.table)

        # Log output
        self.text_log = QTextEdit()
        self.text_log.setReadOnly(True)
        self.text_log.setFixedHeight(150)
        layout.addWidget(self.text_log)

        self.setCentralWidget(central_widget)

        self.worker = None

        # Adjust column widths after the window completes its initial rendering
        QTimer.singleShot(0, self.adjust_initial_columns)

    def adjust_initial_columns(self):
        # Remaining width to distribute to columns 0, 1, 2
        total_width = self.table.viewport().width()
        used_width = self.table.columnWidth(3) + self.table.columnWidth(4)
        available_width = max(0, total_width - used_width)

        segment = available_width // 3
        self.table.setColumnWidth(0, segment)
        self.table.setColumnWidth(1, segment)
        self.table.setColumnWidth(2, available_width - segment * 2)

    def append_log(self, text):
        self.text_log.append(text)

    def add_tasks(self):
        row = self.table.rowCount()
        self.table.insertRow(row)

        # Input File (empty by default)
        item_in = QTableWidgetItem("")
        item_in.setFlags(item_in.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, 0, item_in)

        # Output Directory (empty by default)
        item_out = QTableWidgetItem("")
        item_out.setFlags(item_out.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, 1, item_out)

        # Page Ranges (empty by default until input is chosen)
        item_pages = QTableWidgetItem("")
        item_pages.setFlags(item_pages.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, 2, item_pages)

        # Layout (Checkbox instead of text)
        item_layout = QTableWidgetItem()
        item_layout.setFlags(item_layout.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item_layout.setCheckState(Qt.CheckState.Checked)
        self.table.setItem(row, 3, item_layout)

        # Status
        item_status = QTableWidgetItem("Not started")
        item_status.setFlags(item_status.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, 4, item_status)

    def delete_tasks(self):
        # Delete selected rows (iterate in reverse to avoid index shifting issues)
        selected_rows = sorted(set(idx.row() for idx in self.table.selectedIndexes()),
                               reverse=True)
        for row in selected_rows:
            self.table.removeRow(row)

    def on_cell_double_clicked(self, row, col):
        if col == 0:
            file_path, _ = QFileDialog.getOpenFileName(
                self, "Select Input File", self.table.item(row, col).text(),
                "Documents & Images (*.pdf *.png *.jpg *.jpeg *.bmp *.webp *.tiff);;All Files (*)"
            )
            if file_path:
                self.table.item(row, 0).setText(file_path)
                is_pdf = file_path.lower().endswith('.pdf')
                if not is_pdf:
                    self.table.item(row, 2).setText("")
                    self.table.item(row, 2).setFlags(
                        self.table.item(row, 2).flags() & ~Qt.ItemFlag.ItemIsEditable)
                else:
                    self.table.item(row, 2).setText("1-")
                    self.table.item(row, 2).setFlags(
                        self.table.item(row, 2).flags() | Qt.ItemFlag.ItemIsEditable)

        elif col == 1:
            dir_path = QFileDialog.getExistingDirectory(self, "Select Output Directory",
                                                        self.table.item(row, col).text())
            if dir_path:
                self.table.item(row, 1).setText(dir_path)

    def on_cell_clicked(self, row, col):
        pass

    def start_processing(self, ignore_failed=False):
        if self.worker is not None and self.worker.isRunning():
            logging.warning("OCR worker is busy.")
            return

        tasks = []
        for row in range(self.table.rowCount()):
            status = self.table.item(row, 4).text()
            if status == "Completed" or (ignore_failed and status == "Failed"):
                tasks.append(None)  # Skip completed or ignored failed
                continue

            input_file = self.table.item(row, 0).text().strip()
            output_dir = self.table.item(row, 1).text().strip()
            page_range = self.table.item(row, 2).text().strip()
            layout = self.table.item(row, 3).checkState() == Qt.CheckState.Checked

            # Validation at submission time
            if not input_file or not output_dir:
                logging.error(
                    f"Task on row {row + 1} failed: Empty input or output paths.")
                self.set_row_status(row, "Failed", QColor("red"))
                tasks.append(None)
                continue

            tasks.append({
                'row': row,
                'input': input_file,
                'output': output_dir,
                'pages': page_range,
                'layout': layout
            })

            # Reset status to Not started if it failed before
            self.set_row_status(row, "Not started", None)

        valid_tasks = [t for t in tasks if t is not None]
        if not valid_tasks:
            logging.warning("No queued task to run.")
            return

        self.tasks_controls.setEnabled(False)
        self.worker_controls.setEnabled(True)
        self.table.setEnabled(False)
        self.worker = Worker(valid_tasks)
        self.worker.task_started.connect(self.on_task_started)
        self.worker.task_finished.connect(self.on_task_finished)
        self.worker.all_finished.connect(self.on_all_finished)
        self.worker.start()

    def set_row_status(self, row, status, fg_color):
        item = self.table.item(row, 4)
        item.setText(status)
        for col in range(5):
            table_item = self.table.item(row, col)
            table_item.setData(Qt.ItemDataRole.BackgroundRole, None)
            if fg_color:
                table_item.setForeground(QBrush(fg_color))
            else:
                table_item.setData(Qt.ItemDataRole.ForegroundRole, None)

    def skip_current(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.terminate()
            self.worker.wait()
            if hasattr(self,
                       'current_running_row') and self.current_running_row is not None:
                self.set_row_status(self.current_running_row, "Failed", QColor("red"))
                self.current_running_row = None
            self.start_processing(ignore_failed=True)

    def stop_all(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.terminate()
            self.worker.wait()
            if hasattr(self,
                       'current_running_row') and self.current_running_row is not None:
                self.set_row_status(self.current_running_row, "Failed", QColor("red"))
                self.current_running_row = None
            self.on_all_finished()

    def on_task_started(self, row):
        if self.table.item(row, 4) is None:
            return
        if self.table.item(row, 4).text() == "Completed":
            return
        self.current_running_row = row
        self.set_row_status(row, "In Progress", QColor("blue"))

    def on_task_finished(self, row, success, message):
        if self.table.item(row, 4) is None:
            return
        if success:
            self.set_row_status(row, "Completed", QColor("green"))
        else:
            logging.error(f"Task on row {row + 1} failed: {message}")
            self.set_row_status(row, "Failed", QColor("red"))
        if getattr(self, 'current_running_row', None) == row:
            self.current_running_row = None

    def on_all_finished(self):
        self.tasks_controls.setEnabled(True)
        self.worker_controls.setEnabled(False)
        self.table.setEnabled(True)


if __name__ == '__main__':
    app = QApplication([])
    screen = app.primaryScreen()
    zoom_pct = screen.logicalDotsPerInch() / 96
    font_size = round(12 * zoom_pct)
    app.setStyleSheet(
        f'QWidget {{'
        f'    font-family: "Microsoft YaHei", Calibri, Ubuntu; '
        f'    font-size: {font_size}pt;'
        f'}}'
    )
    window = MainWindow()
    window.show()
    app.exec()
