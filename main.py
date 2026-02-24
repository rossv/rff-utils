import sys
import os
from pathlib import Path

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QListWidget, QListWidgetItem, 
                             QAbstractItemView, QFileDialog, QLabel, QLineEdit, 
                             QMessageBox, QProgressBar)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QIcon

from merge_rff import merge_rff
from visualize import VisualizationDialog
from apptrack import AppTracker

VERSION = "v1.0.1"

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

class MergeThread(QThread):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, input_paths, output_path):
        super().__init__()
        self.input_paths = input_paths
        self.output_path = output_path

    def run(self):
        try:
            def merge_callback(current, total, gid):
                self.progress.emit(current, total, gid)
                
            merge_rff(
                input_paths=self.input_paths,
                output_path=self.output_path,
                progress_every=1,
                progress_callback=merge_callback
            )
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))

class DragDropListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            event.setDropAction(Qt.CopyAction)
            event.accept()
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    file_path = str(url.toLocalFile())
                    if file_path.lower().endswith('.rff'):
                        self.add_file(file_path)
        else:
            super().dropEvent(event)

    def add_file(self, file_path):
        # Prevent duplicates
        for i in range(self.count()):
            if self.item(i).data(Qt.UserRole) == file_path:
                return
        item = QListWidgetItem(Path(file_path).name)
        item.setData(Qt.UserRole, file_path)
        item.setToolTip(file_path)
        self.addItem(item)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"RFF Merger {VERSION}")
        self.setWindowIcon(QIcon(resource_path(os.path.join("assets", "icon.ico"))))
        self.resize(600, 500)
        
        # Telemetry: App Launch
        self.tracker = AppTracker(channel="gui", version=VERSION)
        self.tracker.ping_async()

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # File List
        main_layout.addWidget(QLabel("1. Drag and Drop .rff files here (drag to reorder chronologically):"))
        self.file_list = DragDropListWidget()
        main_layout.addWidget(self.file_list)

        # File List Controls
        list_btn_layout = QHBoxLayout()
        btn_add = QPushButton("Add Files")
        btn_add.clicked.connect(self.browse_input_files)
        btn_remove = QPushButton("Remove Selected")
        btn_remove.clicked.connect(self.remove_selected_files)
        btn_clear = QPushButton("Clear All")
        btn_clear.clicked.connect(self.file_list.clear)
        list_btn_layout.addWidget(btn_add)
        list_btn_layout.addWidget(btn_remove)
        list_btn_layout.addWidget(btn_clear)
        main_layout.addLayout(list_btn_layout)

        # Output Selection
        main_layout.addWidget(QLabel("2. Select Output File:"))
        out_layout = QHBoxLayout()
        self.out_edit = QLineEdit()
        out_layout.addWidget(self.out_edit)
        btn_out_browse = QPushButton("Browse")
        btn_out_browse.clicked.connect(self.browse_output_file)
        out_layout.addWidget(btn_out_browse)
        main_layout.addLayout(out_layout)

        # Action Buttons
        main_layout.addSpacing(10)
        main_layout.addWidget(QLabel("3. Actions:"))
        action_layout = QHBoxLayout()
        
        btn_visualize = QPushButton("Visualize / Statistics")
        btn_visualize.clicked.connect(self.show_visualization)
        action_layout.addWidget(btn_visualize)
        
        self.btn_merge = QPushButton("Merge Files")
        self.btn_merge.setStyleSheet("font-weight: bold; background-color: #4CAF50; color: white; padding: 5px;")
        self.btn_merge.clicked.connect(self.start_merge)
        action_layout.addWidget(self.btn_merge)
        
        btn_help = QPushButton("Help")
        btn_help.clicked.connect(self.show_help)
        action_layout.addWidget(btn_help)
        
        main_layout.addLayout(action_layout)

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.hide()
        main_layout.addWidget(self.progress_bar)
        
        self.status_label = QLabel("Ready")
        main_layout.addWidget(self.status_label)

    def get_file_paths(self):
        paths = []
        for i in range(self.file_list.count()):
            paths.append(self.file_list.item(i).data(Qt.UserRole))
        return paths

    def browse_input_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Select RFF Files", "", "RFF Files (*.rff)")
        for f in files:
            self.file_list.add_file(f)

    def remove_selected_files(self):
        for item in self.file_list.selectedItems():
            self.file_list.takeItem(self.file_list.row(item))

    def browse_output_file(self):
        file, _ = QFileDialog.getSaveFileName(self, "Save Merged RFF", "", "RFF Files (*.rff)")
        if file:
            self.out_edit.setText(file)

    def show_visualization(self):
        paths = self.get_file_paths()
        if not paths:
            QMessageBox.warning(self, "No files", "Please add at least one .rff file to visualize.")
            return
        
        dlg = VisualizationDialog(paths, self)
        dlg.exec_()

    def show_help(self):
        msg = (
            f"RFF Merger {VERSION}\n\n"
            "This tool merges multiple SWMM5-RAIN .rff binary rainfall files into one.\n"
            "- Add files by dragging and dropping them into the list.\n"
            "- Reorder them by dragging items up or down. Files higher in the list are processed first.\n"
            "- Data from files lower in the list will overwrite data from higher files if timestamps overlap.\n"
            "- Click 'Visualize' to preview the rainfall statistics before merging.\n\n"
            "Credits: Ross Volkwein"
        )
        QMessageBox.information(self, "Help & About", msg)

    def start_merge(self):
        input_paths = self.get_file_paths()
        output_path = self.out_edit.text()

        if not input_paths:
            QMessageBox.warning(self, "Error", "No input files selected.")
            return
        if not output_path:
            QMessageBox.warning(self, "Error", "No output file selected.")
            return

        # Disable UI
        self.btn_merge.setEnabled(False)
        self.progress_bar.show()
        self.progress_bar.setValue(0)
        self.status_label.setText("Merging...")

        # Telemetry: Merge attempt
        AppTracker(channel="gui", version=VERSION).ping_async()

        self.thread = MergeThread(input_paths, output_path)
        self.thread.progress.connect(self.update_progress)
        self.thread.finished.connect(self.merge_finished)
        self.thread.error.connect(self.merge_error)
        self.thread.start()

    def update_progress(self, current, total, gid):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.status_label.setText(f"Processing Gauge: {gid} ({current}/{total})")

    def merge_finished(self):
        self.btn_merge.setEnabled(True)
        self.progress_bar.hide()
        self.status_label.setText("Merge completed successfully!")
        QMessageBox.information(self, "Success", f"Files merged successfully into:\n{self.out_edit.text()}")

    def merge_error(self, err_msg):
        self.btn_merge.setEnabled(True)
        self.progress_bar.hide()
        self.status_label.setText("Merge failed.")
        QMessageBox.critical(self, "Error", f"An error occurred during merging:\n{err_msg}")


def main():
    app = QApplication(sys.argv)
    
    # Optional styling
    app.setStyle("Fusion")
    app.setWindowIcon(QIcon(resource_path(os.path.join("assets", "icon.ico"))))

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
