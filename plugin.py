"""Plugin: adds 'Apply QLR file to layers' to the layer-group context menu."""

import os

from qgis.core import Qgis, QgsLayerTreeGroup, QgsMessageLog, QgsSettings
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QMessageBox

from .dialog import ApplyQlrDialog
from .menu_hook import ContextMenuAugmenter
from .qlr_applier import apply_qlr_to_groups

MENU_TEXT = "Apply QLR file to layers"
SETTINGS_FILE = "apply_qlr_to_layers/lastFile"
SETTINGS_SUBGROUPS = "apply_qlr_to_layers/includeSubgroups"
ICON_PATH = os.path.join(os.path.dirname(__file__), "icon.svg")
LOG_TAG = "Apply QLR to layers"


def _exec(obj, *args):
    fn = getattr(obj, "exec", None) or getattr(obj, "exec_")
    return fn(*args)


def _log(message, level_name="Warning"):
    try:
        level = getattr(Qgis.MessageLevel, level_name)
    except AttributeError:
        level = getattr(Qgis, level_name)
    QgsMessageLog.logMessage(message, LOG_TAG, level)


class ApplyQlrToLayersPlugin:
    def __init__(self, iface):
        self.iface = iface
        self._hook = None
        self.icon = QIcon(ICON_PATH)

    # ------------------------------------------------------------------ setup
    def initGui(self):
        view = self.iface.layerTreeView()
        self._hook = ContextMenuAugmenter(view, self._group_at, self._populate_menu)

    def unload(self):
        if self._hook is not None:
            self._hook.dispose()
            self._hook.deleteLater()
        self._hook = None

    # ------------------------------------------------------------ context menu
    def _group_at(self, pos):
        """Group node under the cursor, or None (item only shown for groups)."""
        view = self.iface.layerTreeView()
        idx = view.indexAt(pos)
        if not idx.isValid():
            return None
        node = view.index2node(idx)
        if node is not None and isinstance(node, QgsLayerTreeGroup):
            return node
        return None

    def _populate_menu(self, menu, clicked_group):
        actions = menu.actions()
        if actions and not actions[-1].isSeparator():
            menu.addSeparator()
        action = menu.addAction(self.icon, MENU_TEXT)
        # Defer so the menu closes before the modal dialog opens.
        action.triggered.connect(
            lambda *_: QTimer.singleShot(0, lambda: self.run(self._target_groups(clicked_group))))

    def _target_groups(self, clicked_group):
        """The selected groups if the clicked one is among them, else just it."""
        view = self.iface.layerTreeView()
        try:
            selected = [n for n in view.selectedNodes() if isinstance(n, QgsLayerTreeGroup)]
        except RuntimeError:
            selected = []
        return selected if any(n == clicked_group for n in selected) else [clicked_group]

    # --------------------------------------------------------------------- run
    def run(self, groups):
        parent = self.iface.mainWindow()
        settings = QgsSettings()
        dlg = ApplyQlrDialog(
            parent, MENU_TEXT, self.icon,
            settings.value(SETTINGS_FILE, "", type=str),
            settings.value(SETTINGS_SUBGROUPS, True, type=bool),
        )
        if not _exec(dlg):
            return
        path = dlg.qlr_path()
        include_sub = dlg.include_subgroups()
        settings.setValue(SETTINGS_FILE, path)
        settings.setValue(SETTINGS_SUBGROUPS, include_sub)

        try:
            result = apply_qlr_to_groups(path, groups, self.iface, include_sub)
        except Exception as exc:
            QMessageBox.critical(parent, MENU_TEXT, str(exc))
            return

        self._report(parent, path, result)

    def _report(self, parent, path, result):
        bar = self.iface.messageBar()
        summary = "Applied {} style(s) from {}.".format(
            len(result.applied), os.path.basename(path))

        problems = result.failed or result.unmatched_layers or result.unmatched_styles
        if not result.applied:
            bar.pushWarning(MENU_TEXT, "No matching layers found in the group. " + summary)
        elif result.failed:
            bar.pushWarning(MENU_TEXT, summary + " Some layers failed.")
        else:
            bar.pushSuccess(MENU_TEXT, summary)

        if not problems and result.applied:
            return

        lines = []
        if result.applied:
            lines.append("Applied:")
            lines += ["  - " + s for s in result.applied]
        if result.failed:
            lines.append("\nFailed:")
            lines += ["  - {}: {}".format(n, e) for n, e in result.failed]
        if result.unmatched_layers:
            lines.append("\nLayers in the group with no matching style in the QLR:")
            lines += ["  - " + n for n in result.unmatched_layers]
        if result.unmatched_styles:
            lines.append("\nQLR styles that matched no layer in the group:")
            lines += ["  - " + n for n in result.unmatched_styles]

        box = QMessageBox(parent)
        box.setWindowTitle(MENU_TEXT)
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(summary)
        box.setDetailedText("\n".join(lines))
        _exec(box)
