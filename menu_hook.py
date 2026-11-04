"""Non-invasive hook that appends an action to a view's existing context menu.

Why this design: QGIS lets only one menu provider be set on the layer tree view,
and replacing it (or swallowing the right-click and showing a menu of our own)
breaks every other plugin that customises the same menu.  Instead we let the
right-click pass through untouched, so QGIS and all other plugins build and show
their menu normally, and just add one action to that menu just before it is
displayed (QMenu.aboutToShow).

Flow:
  1. A passive filter on the view's viewport sees the ContextMenu event, notes
     whether it is on a relevant node, and always returns False (never consumes).
  2. If relevant, a short-lived application-wide filter waits for the next
     top-level QMenu to be polished and connects to its aboutToShow signal.
  3. In aboutToShow (all other plugins have finished building the menu) the
     action is appended.
The application-wide filter is installed only for the instant of the right-click
and removed again, so there is no lasting per-event overhead.
"""

from qgis.PyQt.QtCore import QEvent, QObject, QTimer
from qgis.PyQt.QtWidgets import QApplication, QMenu


class ContextMenuAugmenter(QObject):
    def __init__(self, view, node_at_pos, populate, parent=None):
        """
        view         -- the tree view whose context menu is extended
        node_at_pos  -- callable(QPoint) -> object or None; None = do not extend
        populate     -- callable(QMenu, object): add the action(s) to the menu
        """
        super().__init__(parent or view)
        self._view = view
        self._viewport = view.viewport()
        self._node_at_pos = node_at_pos
        self._populate = populate
        self._pending = None          # object clicked, awaiting its menu
        self._app_filter_on = False
        self._viewport.installEventFilter(self)

    # ---------------------------------------------------------------- lifetime
    def dispose(self):
        self._stop_waiting()
        try:
            self._viewport.removeEventFilter(self)
        except RuntimeError:  # viewport already deleted (QGIS closing)
            pass

    # ------------------------------------------------------------ event filter
    def eventFilter(self, obj, event):
        if obj is self._viewport:
            if event.type() == QEvent.Type.ContextMenu:
                self._on_context_menu(event)
            return False  # NEVER consume: others must see the event too

        # application-wide phase: waiting for the menu to appear
        if (self._pending is not None and event.type() == QEvent.Type.Polish
                and isinstance(obj, QMenu)):
            self._hook_menu(obj)
        return False

    # ------------------------------------------------------------------ phases
    def _on_context_menu(self, event):
        try:
            target = self._node_at_pos(event.pos())
        except Exception:
            target = None
        self._stop_waiting()
        if target is None:
            return
        self._pending = target
        app = QApplication.instance()
        app.installEventFilter(self)
        self._app_filter_on = True
        # The menu is created and shown synchronously within this same event
        # dispatch, before the nested event loop of menu.exec() processes this
        # timer. If no menu appears at all, this cleans up.
        QTimer.singleShot(0, self._stop_waiting)

    def _hook_menu(self, menu):
        target = self._pending
        self._stop_waiting()
        done = []

        def add():
            if done:
                return
            done.append(True)
            try:
                menu.aboutToShow.disconnect(add)
            except (TypeError, RuntimeError):
                pass
            self._populate(menu, target)

        menu.aboutToShow.connect(add)

    def _stop_waiting(self):
        self._pending = None
        if self._app_filter_on:
            self._app_filter_on = False
            app = QApplication.instance()
            if app is not None:
                app.removeEventFilter(self)
