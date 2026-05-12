import logging

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, QTimer
from PyQt6.QtGui import QColor, QBrush
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QFileDialog,
    QTextEdit, QHeaderView, QAbstractItemView
)

from chandra.predict import predict_pdf, predict_image


STATUS_DRAFT = "Draft"
STATUS_QUEUED = "Queued"
STATUS_IN_PROGRESS = "Processing"
STATUS_COMPLETED = "Completed"
STATUS_FAILED = "Failed"

STATUS_COLORS = {
    STATUS_QUEUED: QColor("gray"),
    STATUS_IN_PROGRESS: QColor("blue"),
    STATUS_COMPLETED: QColor("green"),
    STATUS_FAILED: QColor("red"),
}


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
    task_finished = pyqtSignal(bool, str)

    def __init__(self, task, parent=None):
        super().__init__(parent)
        self.task = task

    def run(self):
        try:
            input_file = self.task['input']
            output_dir = self.task['output']
            page_range = self.task['pages']
            layout = self.task['layout']

            if input_file.lower().endswith('.pdf'):
                predict_pdf(input_file, output_dir, page_range, layout)
            else:
                predict_image(input_file, output_dir, layout)
            self.task_finished.emit(True, "Completed")
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.task_finished.emit(False, str(e))


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

        self.btn_add = QPushButton("Draft")
        self.btn_add.clicked.connect(self.add_tasks)
        self.btn_delete = QPushButton("Delete")
        self.btn_delete.clicked.connect(self.delete_tasks)
        self.btn_submit = QPushButton("Submit")
        self.btn_submit.clicked.connect(self.submit_tasks)
        self.btn_withdraw = QPushButton("Withdraw")
        self.btn_withdraw.clicked.connect(self.withdraw_tasks)
        self.btn_redo = QPushButton("Redo")
        self.btn_redo.clicked.connect(self.redo_tasks)
        self.btn_terminate = QPushButton("Terminate")
        self.btn_terminate.clicked.connect(self.terminate_all)

        for b in (self.btn_add, self.btn_delete, self.btn_submit,
                  self.btn_withdraw, self.btn_redo, self.btn_terminate):
            controls_layout.addWidget(b)
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

        layout.addWidget(self.table)

        # Log output
        self.text_log = QTextEdit()
        self.text_log.setReadOnly(True)
        self.text_log.setFixedHeight(150)
        layout.addWidget(self.text_log)

        self.setCentralWidget(central_widget)

        self.worker = None
        self.current_running_row = None

        # Adjust column widths after the window completes its initial rendering
        QTimer.singleShot(0, self.adjust_initial_columns)

    def adjust_initial_columns(self):
        total_width = self.table.viewport().width()
        used_width = self.table.columnWidth(3) + self.table.columnWidth(4)
        available_width = max(0, total_width - used_width)

        segment = available_width // 3
        self.table.setColumnWidth(0, segment)
        self.table.setColumnWidth(1, segment)
        self.table.setColumnWidth(2, available_width - segment * 2)

    def append_log(self, text):
        self.text_log.append(text)

    # ------- Row state helpers -------

    def _row_status(self, row):
        item = self.table.item(row, 4)
        return item.text() if item else ""

    def _set_row_editable(self, row, editable):
        # Cols 0, 1: not directly typable; double-click dialog is gated by status.
        for col in (0, 1):
            it = self.table.item(row, col)
            if it is not None:
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)

        item_pages = self.table.item(row, 2)
        if item_pages is not None:
            input_file = self.table.item(row, 0).text() if self.table.item(row, 0) else ""
            is_pdf = input_file.lower().endswith('.pdf')
            if editable and is_pdf:
                item_pages.setFlags(item_pages.flags() | Qt.ItemFlag.ItemIsEditable)
            else:
                item_pages.setFlags(item_pages.flags() & ~Qt.ItemFlag.ItemIsEditable)

        item_layout = self.table.item(row, 3)
        if item_layout is not None:
            flags = item_layout.flags()
            if editable:
                flags |= Qt.ItemFlag.ItemIsUserCheckable
                flags |= Qt.ItemFlag.ItemIsEnabled
            else:
                flags &= ~Qt.ItemFlag.ItemIsUserCheckable
            item_layout.setFlags(flags)

        item_status = self.table.item(row, 4)
        if item_status is not None:
            item_status.setFlags(item_status.flags() & ~Qt.ItemFlag.ItemIsEditable)

    def _set_row_status(self, row, status):
        item = self.table.item(row, 4)
        if item is None:
            return
        item.setText(status)
        color = STATUS_COLORS.get(status)
        for col in range(5):
            table_item = self.table.item(row, col)
            if table_item is None:
                continue
            if color:
                table_item.setForeground(QBrush(color))
            else:
                table_item.setData(Qt.ItemDataRole.ForegroundRole, None)

    def _row_to_task(self, row):
        return {
            'input': self.table.item(row, 0).text().strip(),
            'output': self.table.item(row, 1).text().strip(),
            'pages': self.table.item(row, 2).text().strip(),
            'layout': self.table.item(row, 3).checkState() == Qt.CheckState.Checked,
        }

    def _selected_rows(self):
        return sorted(set(idx.row() for idx in self.table.selectedIndexes()))

    # ------- Buttons -------

    def add_tasks(self):
        row = self.table.rowCount()
        self.table.insertRow(row)

        item_in = QTableWidgetItem("")
        self.table.setItem(row, 0, item_in)

        item_out = QTableWidgetItem("")
        self.table.setItem(row, 1, item_out)

        item_pages = QTableWidgetItem("")
        self.table.setItem(row, 2, item_pages)

        item_layout = QTableWidgetItem()
        item_layout.setCheckState(Qt.CheckState.Checked)
        self.table.setItem(row, 3, item_layout)

        item_status = QTableWidgetItem(STATUS_DRAFT)
        self.table.setItem(row, 4, item_status)

        self._set_row_editable(row, True)

    def delete_tasks(self):
        for row in sorted(self._selected_rows(), reverse=True):
            if self.current_running_row == row and self.worker is not None \
                    and self.worker.isRunning():
                self._terminate_worker()
                self.current_running_row = None
            elif self.current_running_row is not None \
                    and row < self.current_running_row:
                self.current_running_row -= 1
            self.table.removeRow(row)
        self._try_start_next()

    def submit_tasks(self):
        rows = self._selected_rows()
        if not rows:
            rows = [r for r in range(self.table.rowCount())
                    if self._row_status(r) == STATUS_DRAFT]

        for row in rows:
            if self._row_status(row) != STATUS_DRAFT:
                continue
            task = self._row_to_task(row)
            if not task['input'] or not task['output']:
                logging.error(
                    f"Task on row {row + 1} cannot be submitted: "
                    f"empty input or output path.")
                continue
            self._set_row_editable(row, False)
            self._set_row_status(row, STATUS_QUEUED)
        self._try_start_next()

    def withdraw_tasks(self):
        for row in self._selected_rows():
            self._withdraw_row(row)
        self._try_start_next()

    def _withdraw_row(self, row):
        status = self._row_status(row)
        if status == STATUS_DRAFT:
            return
        if status == STATUS_IN_PROGRESS and self.current_running_row == row:
            if self.worker is not None and self.worker.isRunning():
                self._terminate_worker()
            self.current_running_row = None
        self._set_row_status(row, STATUS_DRAFT)
        self._set_row_editable(row, True)

    def redo_tasks(self):
        for row in self._selected_rows():
            status = self._row_status(row)
            if status == STATUS_DRAFT:
                continue
            if status == STATUS_IN_PROGRESS and self.current_running_row == row:
                if self.worker is not None and self.worker.isRunning():
                    self._terminate_worker()
                self.current_running_row = None
            self._set_row_editable(row, False)
            self._set_row_status(row, STATUS_QUEUED)
        self._try_start_next()

    def terminate_all(self):
        if self.worker is not None and self.worker.isRunning():
            self._terminate_worker()
        self.current_running_row = None
        for row in range(self.table.rowCount()):
            if self._row_status(row) != STATUS_DRAFT:
                self._set_row_status(row, STATUS_DRAFT)
                self._set_row_editable(row, True)

    def _terminate_worker(self):
        try:
            self.worker.task_finished.disconnect(self.on_task_finished)
        except (TypeError, RuntimeError):
            pass
        self.worker.terminate()
        self.worker.wait()
        self.worker = None

    # ------- Table interaction -------

    def on_cell_double_clicked(self, row, col):
        if self._row_status(row) != STATUS_DRAFT:
            return

        if col == 0:
            file_path, _ = QFileDialog.getOpenFileName(
                self, "Select Input File", self.table.item(row, col).text(),
                "Documents & Images (*.pdf *.png *.jpg *.jpeg *.bmp *.webp *.tiff);;All Files (*)"
            )
            if file_path:
                self.table.item(row, 0).setText(file_path)
                is_pdf = file_path.lower().endswith('.pdf')
                pages_item = self.table.item(row, 2)
                if not is_pdf:
                    pages_item.setText("")
                    pages_item.setFlags(
                        pages_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                else:
                    if not pages_item.text():
                        pages_item.setText("1-")
                    pages_item.setFlags(
                        pages_item.flags() | Qt.ItemFlag.ItemIsEditable)

        elif col == 1:
            dir_path = QFileDialog.getExistingDirectory(self, "Select Output Directory",
                                                        self.table.item(row, col).text())
            if dir_path:
                self.table.item(row, 1).setText(dir_path)

    # ------- Worker queue -------

    def _try_start_next(self):
        if self.worker is not None and self.worker.isRunning():
            return
        for row in range(self.table.rowCount()):
            if self._row_status(row) == STATUS_QUEUED:
                self._start_row(row)
                return

    def _start_row(self, row):
        task = self._row_to_task(row)
        if not task['input'] or not task['output']:
            logging.error(
                f"Task on row {row + 1} failed: empty input or output paths.")
            self._set_row_status(row, STATUS_FAILED)
            QTimer.singleShot(0, self._try_start_next)
            return

        self.current_running_row = row
        self._set_row_status(row, STATUS_IN_PROGRESS)
        self.worker = Worker(task)
        self.worker.task_finished.connect(self.on_task_finished)
        self.worker.start()

    def on_task_finished(self, success, message):
        row = self.current_running_row
        self.current_running_row = None
        if self.worker is not None:
            # run() has just emitted task_finished and is about to return.
            # wait() ensures the QThread is fully finished before we drop
            # the last Python reference; otherwise GC of a still-running
            # QThread aborts the process with no traceback (large negative
            # exit code on Windows).
            self.worker.wait()
            self.worker.deleteLater()
            self.worker = None

        if row is not None and self.table.item(row, 4) is not None \
                and self._row_status(row) == STATUS_IN_PROGRESS:
            if success:
                self._set_row_status(row, STATUS_COMPLETED)
            else:
                logging.error(f"Task on row {row + 1} failed: {message}")
                self._set_row_status(row, STATUS_FAILED)

        self._try_start_next()


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
