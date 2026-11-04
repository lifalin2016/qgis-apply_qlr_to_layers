import os

from qgis.PyQt.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QVBoxLayout,
)


class ApplyQlrDialog(QDialog):
    """Pick a QLR file and choose whether subgroups are included."""

    def __init__(self, parent, title, icon, start_path="", include_subgroups=True):
        super().__init__(parent)
        self.setWindowTitle(title)
        if icon is not None:
            self.setWindowIcon(icon)
        self.setMinimumWidth(500)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("QLR file to apply:"))

        row = QHBoxLayout()
        self.path_edit = QLineEdit(start_path)
        self.path_edit.setPlaceholderText("Select a .qlr file...")
        browse = QPushButton("Browse...")
        row.addWidget(self.path_edit, 1)
        row.addWidget(browse)
        layout.addLayout(row)

        self.sub_check = QCheckBox("Include layers in subgroups")
        self.sub_check.setChecked(include_subgroups)
        self.sub_check.setToolTip(
            "When checked, layers in nested groups below the selected group are styled too.")
        layout.addWidget(self.sub_check)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(self.buttons)

        browse.clicked.connect(self._browse)
        self.path_edit.textChanged.connect(self._validate)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self._validate()

    def _browse(self):
        current = self.path_edit.text().strip()
        start = os.path.dirname(current) if current else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select QLR file to apply", start,
            "QGIS layer definition (*.qlr);;All files (*)")
        if path:
            self.path_edit.setText(path)

    def _validate(self):
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(os.path.isfile(self.path_edit.text().strip()))

    def qlr_path(self):
        return self.path_edit.text().strip()

    def include_subgroups(self):
        return self.sub_check.isChecked()
