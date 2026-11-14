import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from image_engine import AdjustmentParams, ImageEngine


class PreviewLabel(QLabel):
    def __init__(self):
        super().__init__("点击右侧“导入图片”开始")
        self._source_pixmap = QPixmap()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(360, 280)
        self.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Ignored,
        )
        self.setStyleSheet("color: #8b949e; background: #161b22;")

    def set_image(self, image) -> None:
        height, width, channels = image.shape
        qimage = QImage(
            image.data,
            width,
            height,
            channels * width,
            QImage.Format.Format_RGB888,
        ).copy()
        self._source_pixmap = QPixmap.fromImage(qimage)
        self._update_pixmap()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_pixmap()

    def _update_pixmap(self) -> None:
        if self._source_pixmap.isNull() or self.width() <= 0 or self.height() <= 0:
            return
        pixmap = self._source_pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(pixmap)


class SliderRow(QWidget):
    def __init__(self, title: str):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        header = QHBoxLayout()
        title_label = QLabel(title)
        self.value_label = QLabel("0")
        self.value_label.setObjectName("sliderValue")
        self.value_label.setMinimumWidth(38)
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        header.addWidget(title_label)
        header.addStretch()
        header.addWidget(self.value_label)
        layout.addLayout(header)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(-100, 100)
        self.slider.setValue(0)
        self.slider.setSingleStep(1)
        self.slider.setPageStep(10)
        self.slider.valueChanged.connect(self._on_value_changed)
        layout.addWidget(self.slider)

    def value(self) -> int:
        return self.slider.value()

    def set_value(self, value: int) -> None:
        self.slider.setValue(value)
        self.value_label.setText(self._format_value(self.slider.value()))

    def _on_value_changed(self, value: int) -> None:
        self.value_label.setText(self._format_value(value))

    @staticmethod
    def _format_value(value: int) -> str:
        return f"+{value}" if value > 0 else str(value)


class MainWindow(QMainWindow):
    FILE_FILTER = (
        "所有支持的图片 (*.jpg *.jpeg *.png *.cr2 *.cr3 *.nef *.nrw *.arw "
        "*.srf *.sr2 *.dng *.orf *.rw2 *.raf *.pef *.srw *.raw);;"
        "常规图片 (*.jpg *.jpeg *.png);;"
        "RAW 图片 (*.cr2 *.cr3 *.nef *.nrw *.arw *.srf *.sr2 *.dng "
        "*.orf *.rw2 *.raf *.pef *.srw *.raw)"
    )

    def __init__(self):
        super().__init__()
        self.engine = ImageEngine(preview_max_side=1400)
        self.current_file_path: Path | None = None
        self.slider_rows: dict[str, SliderRow] = {}

        self.setWindowTitle("轻影暗房 - MVP")
        self.resize(1200, 760)
        self.setMinimumSize(900, 600)
        self._build_ui()
        self._apply_styles()

        # 每次滑块变化都重启定时器，停止操作 90ms 后才执行一次运算。
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(90)
        self._debounce_timer.timeout.connect(self._update_preview)

        self._set_image_controls_enabled(False)

    def _build_ui(self) -> None:
        central = QWidget()
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(12)
        self.setCentralWidget(central)

        preview_frame = QFrame()
        preview_frame.setObjectName("previewFrame")
        preview_layout = QVBoxLayout(preview_frame)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_label = PreviewLabel()
        preview_layout.addWidget(self.preview_label)
        root_layout.addWidget(preview_frame, 1)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        scroll_area.setFixedWidth(330)
        root_layout.addWidget(scroll_area)

        control_panel = QWidget()
        control_panel.setObjectName("controlPanel")
        scroll_area.setWidget(control_panel)
        controls = QVBoxLayout(control_panel)
        controls.setContentsMargins(18, 18, 18, 18)
        controls.setSpacing(12)

        title = QLabel("照片调整")
        title.setObjectName("panelTitle")
        controls.addWidget(title)

        self.import_button = QPushButton("导入图片")
        self.import_button.setObjectName("importButton")
        self.import_button.setMinimumHeight(40)
        self.import_button.clicked.connect(self._import_image)
        controls.addWidget(self.import_button)

        self.file_info_label = QLabel("尚未导入图片")
        self.file_info_label.setObjectName("fileInfo")
        self.file_info_label.setWordWrap(True)
        controls.addWidget(self.file_info_label)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setObjectName("separator")
        controls.addWidget(separator)

        for key, title_text in (
            ("exposure", "曝光度 / 亮度"),
            ("contrast", "对比度"),
            ("saturation", "饱和度"),
            ("temperature", "色温"),
        ):
            row = SliderRow(title_text)
            row.slider.valueChanged.connect(self._schedule_preview_update)
            row.slider.sliderReleased.connect(self._update_preview_immediately)
            self.slider_rows[key] = row
            controls.addWidget(row)

        self.reset_button = QPushButton("重置参数")
        self.reset_button.clicked.connect(self._reset_adjustments)
        controls.addWidget(self.reset_button)
        controls.addStretch()

        hint = QLabel("提示：拖动滑块时仅处理缩小预览图；导出时重新渲染全分辨率原图。")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        controls.addWidget(hint)

        self.export_button = QPushButton("导出高画质 JPG")
        self.export_button.setObjectName("exportButton")
        self.export_button.setMinimumHeight(40)
        self.export_button.clicked.connect(self._export_image)
        controls.addWidget(self.export_button)

        self.statusBar().showMessage("就绪")

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #0d1117; color: #e6edf3; }
            QFrame#previewFrame { background: #161b22; border: 1px solid #30363d; }
            QWidget#controlPanel { background: #161b22; }
            QLabel#panelTitle { font-size: 22px; font-weight: 600; }
            QLabel#fileInfo, QLabel#hint { color: #8b949e; font-size: 12px; }
            QLabel#sliderValue { color: #79c0ff; }
            QFrame#separator { color: #30363d; }
            QPushButton {
                background: #21262d; border: 1px solid #30363d;
                border-radius: 5px; padding: 7px 12px;
            }
            QPushButton:hover { background: #30363d; }
            QPushButton:disabled { color: #656d76; background: #161b22; }
            QPushButton#importButton { background: #1f6feb; border: none; }
            QPushButton#importButton:hover { background: #388bfd; }
            QPushButton#exportButton { background: #238636; border: none; }
            QPushButton#exportButton:hover { background: #2ea043; }
            QSlider::groove:horizontal {
                height: 4px; background: #30363d; border-radius: 2px;
            }
            QSlider::sub-page:horizontal { background: #388bfd; border-radius: 2px; }
            QSlider::handle:horizontal {
                width: 16px; margin: -6px 0; border-radius: 8px; background: #e6edf3;
            }
            QStatusBar { color: #8b949e; background: #161b22; }
            QScrollArea { background: #161b22; }
            """
        )

    def _import_image(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self, "导入图片", "", self.FILE_FILTER
        )
        if not file_path:
            return

        self.import_button.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            self.engine.load_image(file_path)
        except Exception as exc:
            QMessageBox.critical(self, "导入失败", f"无法读取图片：\n{exc}")
            self.statusBar().showMessage("图片导入失败")
            return
        finally:
            QApplication.restoreOverrideCursor()
            self.import_button.setEnabled(True)

        self.current_file_path = Path(file_path)
        self._set_all_sliders(0)
        self.preview_label.set_image(self.engine.preview_image)
        self._set_image_controls_enabled(True)

        original_height, original_width = self.engine.original_image.shape[:2]
        preview_height, preview_width = self.engine.preview_image.shape[:2]
        self.file_info_label.setText(
            f"{self.current_file_path.name}\n"
            f"原图：{original_width} × {original_height}\n"
            f"预览：{preview_width} × {preview_height}"
        )
        self.statusBar().showMessage(f"已导入：{self.current_file_path.name}")

    def _export_image(self) -> None:
        if not self.engine.has_image:
            return

        suggested_name = "edited.jpg"
        if self.current_file_path is not None:
            suggested_name = f"{self.current_file_path.stem}_edited.jpg"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出高画质 JPG",
            suggested_name,
            "JPEG 图片 (*.jpg *.jpeg)",
        )
        if not file_path:
            return
        if Path(file_path).suffix.lower() not in {".jpg", ".jpeg"}:
            file_path += ".jpg"

        self.import_button.setEnabled(False)
        self.export_button.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            # 导出重新处理 original_image，不使用缩小的 preview_image。
            full_image = self.engine.render_full_resolution(self._current_params())
            self.engine.save_jpeg(full_image, file_path, quality=95)
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", f"无法保存图片：\n{exc}")
            self.statusBar().showMessage("图片导出失败")
            return
        finally:
            QApplication.restoreOverrideCursor()
            self.import_button.setEnabled(True)
            self.export_button.setEnabled(self.engine.has_image)

        self.statusBar().showMessage(f"已导出：{file_path}", 10000)
        QMessageBox.information(self, "导出完成", f"高画质 JPG 已保存至：\n{file_path}")

    def _schedule_preview_update(self) -> None:
        if self.engine.has_image:
            self._debounce_timer.start()

    def _update_preview_immediately(self) -> None:
        if self.engine.has_image:
            self._debounce_timer.stop()
            self._update_preview()

    def _update_preview(self) -> None:
        if not self.engine.has_image:
            return
        try:
            processed = self.engine.render_preview(self._current_params())
            self.preview_label.set_image(processed)
        except Exception as exc:
            self._debounce_timer.stop()
            QMessageBox.critical(self, "预览失败", f"无法更新预览：\n{exc}")

    def _reset_adjustments(self) -> None:
        self._debounce_timer.stop()
        self._set_all_sliders(0)
        self._update_preview()
        self.statusBar().showMessage("已重置全部调整参数")

    def _set_all_sliders(self, value: int) -> None:
        for row in self.slider_rows.values():
            row.slider.blockSignals(True)
            row.set_value(value)
            row.slider.blockSignals(False)

    def _set_image_controls_enabled(self, enabled: bool) -> None:
        self.export_button.setEnabled(enabled)
        self.reset_button.setEnabled(enabled)
        for row in self.slider_rows.values():
            row.slider.setEnabled(enabled)

    def _current_params(self) -> AdjustmentParams:
        return AdjustmentParams(
            exposure=self.slider_rows["exposure"].value(),
            contrast=self.slider_rows["contrast"].value(),
            saturation=self.slider_rows["saturation"].value(),
            temperature=self.slider_rows["temperature"].value(),
        )


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("轻影暗房")
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
