import sys
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
                             QComboBox)
from PyQt5.QtCore import QThread, pyqtSignal, Qt
import pyqtgraph as pg
import datetime

from merge_rff import read_rff_header_and_directory, read_gauge_records

# Convert Excel serial date to Python datetime
def excel_to_datetime(excel_date):
    # Excel origin is 1899-12-30
    dt = datetime.datetime(1899, 12, 30) + datetime.timedelta(days=excel_date)
    return dt

class DataProcessorThread(QThread):
    finished = pyqtSignal(dict, list) # stats, plot_data
    error = pyqtSignal(str)

    def __init__(self, file_paths):
        super().__init__()
        self.file_paths = file_paths

    def run(self):
        try:
            stats = {
                "file_count": len(self.file_paths),
                "gauge_count": 0,
                "active_gauges": 0,
                "empty_gauges_list": [],
                "total_points": 0,
                "min_date": float('inf'),
                "max_date": float('-inf'),
                "max_rain": 0.0
            }
            plot_data = [] # List of tuples (times, values) for each gauge of first file

            if not self.file_paths:
                self.finished.emit(stats, plot_data)
                return

            # Read first file for plot
            rff_first = read_rff_header_and_directory(self.file_paths[0])
            stats["gauge_count"] = rff_first.gauge_count
            
            all_gauges = set(entry.gauge_id for entry in rff_first.directory)
            gauges_with_data = set()

            # Process all files for stats
            for path in self.file_paths:
                rff = read_rff_header_and_directory(path)
                for entry in rff.directory:
                    recs = read_gauge_records(rff.path, entry)
                    stats["total_points"] += len(recs)
                    if recs:
                        gauges_with_data.add(entry.gauge_id)
                        
                        times, values = zip(*recs)
                        c_min_time = min(times)
                        c_max_time = max(times)
                        c_max_val = max(values)
                        
                        stats["min_date"] = min(stats["min_date"], c_min_time)
                        stats["max_date"] = max(stats["max_date"], c_max_time)
                        stats["max_rain"] = max(stats["max_rain"], c_max_val)
                        
                        # Grab the first file's gauges for plotting to keep it light
                        if path == self.file_paths[0]:
                            plot_data.append((times, values, entry.gauge_id))
            
            empty_gauges = all_gauges - gauges_with_data
            stats["active_gauges"] = len(gauges_with_data)
            stats["empty_gauges_list"] = sorted(list(empty_gauges))
            
            self.finished.emit(stats, plot_data)
        except Exception as e:
            self.error.emit(str(e))

class VisualizationDialog(QDialog):
    def __init__(self, file_paths, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Data Statistics & Visualization")
        self.resize(800, 600)
        self.file_paths = file_paths

        layout = QVBoxLayout(self)

        self.info_label = QLabel("Analyzing data...")
        self.info_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.info_label)

        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Statistic", "Value"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        layout.addWidget(self.table)

        # Plot widget and selector
        selector_layout = QHBoxLayout()
        selector_layout.addWidget(QLabel("Select Gauge:"))
        self.gauge_combo = QComboBox()
        self.gauge_combo.currentIndexChanged.connect(self.on_gauge_selected)
        selector_layout.addWidget(self.gauge_combo)
        selector_layout.addStretch()
        layout.addLayout(selector_layout)

        axis = pg.DateAxisItem(orientation='bottom')
        self.plot_widget = pg.PlotWidget(title="Rainfall Data Preview", axisItems={'bottom': axis})
        self.plot_widget.setLabel('left', 'Rainfall', units='in/mm')
        self.plot_widget.setLabel('bottom', 'Time (Date)')
        self.plot_widget.showGrid(x=True, y=True)
        layout.addWidget(self.plot_widget)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        # Start thread
        self.thread = DataProcessorThread(file_paths)
        self.thread.finished.connect(self.on_processing_finished)
        self.thread.error.connect(self.on_processing_error)
        self.thread.start()

    def on_processing_finished(self, stats, plot_data):
        self.info_label.setText(f"Analysis complete for {stats['file_count']} files.")
        
        # Populate table
        stat_rows = []
        if stats['total_points'] > 0:
            min_dt = excel_to_datetime(stats['min_date']).strftime("%Y-%m-%d %H:%M:%S")
            max_dt = excel_to_datetime(stats['max_date']).strftime("%Y-%m-%d %H:%M:%S")
            
            empty_text = ", ".join(stats['empty_gauges_list']) if stats['empty_gauges_list'] else "None"
            
            stat_rows = [
                ("Total Files", str(stats['file_count'])),
                ("Expected Gauges", str(stats['gauge_count'])),
                ("Gauges with Data", f"{stats['active_gauges']} ({stats['gauge_count'] - stats['active_gauges']} empty)"),
                ("Empty Gauges List", empty_text),
                ("Total Data Points", f"{stats['total_points']:,}"),
                ("Start Date", min_dt),
                ("End Date", max_dt),
                ("Max Rainfall", f"{stats['max_rain']:.4f}")
            ]
        else:
            stat_rows = [("Error", "No data points found")]

        self.table.setRowCount(len(stat_rows))
        for row, (k, v) in enumerate(stat_rows):
            self.table.setItem(row, 0, QTableWidgetItem(k))
            self.table.setItem(row, 1, QTableWidgetItem(v))
        self.table.resizeRowsToContents()

        self.plot_data_map = {gid: (times, values) for times, values, gid in plot_data}
        
        if self.plot_data_map:
            self.gauge_combo.blockSignals(True)
            self.gauge_combo.clear()
            self.gauge_combo.addItems(list(self.plot_data_map.keys()))
            self.gauge_combo.blockSignals(False)
            
            # Select the first gauge and plot
            if self.gauge_combo.count() > 0:
                self.on_gauge_selected(0)

    def on_gauge_selected(self, index):
        if index < 0:
            return
        gid = self.gauge_combo.currentText()
        if gid in self.plot_data_map:
            times, values = self.plot_data_map[gid]
            unix_times = [((t - 25569) * 86400) for t in times]
            self.plot_widget.clear()
            self.plot_widget.plot(unix_times, list(values), pen='b', name=gid)
            self.plot_widget.setTitle(f"Rainfall Data Preview - Gauge: {gid}")

    def on_processing_error(self, err_msg):
        self.info_label.setText(f"Error analyzing data: {err_msg}")
