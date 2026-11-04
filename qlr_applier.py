"""Core logic: read styles from a QLR file and apply them to matching layers."""

import os

import qgis.core as qcore
from qgis.core import (
    Qgis,
    QgsLayerTreeLayer,
    QgsPathResolver,
    QgsProject,
    QgsReadWriteContext,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QByteArray
from qgis.PyQt.QtXml import QDomDocument

# Match layer names case-sensitively. Set to False for case-insensitive matching.
CASE_SENSITIVE = True

# QLR "type" attribute -> PyQGIS class name used to recognise target layers
_TYPE_CLASSES = (
    ("vector-tile", "QgsVectorTileLayer"),
    ("point-cloud", "QgsPointCloudLayer"),
    ("mesh", "QgsMeshLayer"),
    ("raster", "QgsRasterLayer"),
    ("vector", "QgsVectorLayer"),
)


def _norm_name(name):
    name = (name or "").strip()
    return name if CASE_SENSITIVE else name.casefold()


def layer_type_key(layer):
    for key, clsname in _TYPE_CLASSES:
        cls = getattr(qcore, clsname, None)
        if cls is not None and isinstance(layer, cls):
            return key
    return "other"


def _geometry_enum_table():
    """Map the QGIS geometry-type enum to simple strings (works on QGIS 3.22 - 4.x)."""
    G = getattr(Qgis, "GeometryType", None)
    if G is not None and hasattr(G, "Point"):
        return {G.Point: "point", G.Line: "line", G.Polygon: "polygon",
                G.Null: "none", G.Unknown: "unknown"}
    W = qcore.QgsWkbTypes
    return {W.PointGeometry: "point", W.LineGeometry: "line",
            W.PolygonGeometry: "polygon", W.NullGeometry: "none",
            W.UnknownGeometry: "unknown"}


def layer_geometry_kind(layer):
    """'point' | 'line' | 'polygon' | 'none' | 'unknown' for a vector layer."""
    try:
        return _geometry_enum_table().get(layer.geometryType(), "unknown")
    except Exception:
        return "unknown"


def _qlr_geometry_kind(element):
    """Geometry kind of a <maplayer> element in a QLR file."""
    text = element.attribute("geometry", "").strip().lower()
    if not text:
        text = element.firstChildElement("wkbType").text().strip().lower()
    if not text:
        return "unknown"
    if text.startswith("no geometry") or text == "nogeometry" or text == "none":
        return "none"
    if "point" in text:
        return "point"
    if "line" in text or "curve" in text:
        return "line"
    if "polygon" in text or "surface" in text or "triangle" in text or "tin" == text:
        return "polygon"
    return "unknown"


class QlrStyle:
    def __init__(self, name, layer_type, kind, element):
        self.name = name
        self.layer_type = layer_type
        self.kind = kind
        self.element = element  # QDomElement; its document must stay alive

    def label(self):
        if self.layer_type == "vector":
            return "{} ({})".format(self.name, self.kind)
        return "{} ({})".format(self.name, self.layer_type)


class QlrFile:
    def __init__(self, path):
        self.path = path
        self.doc = QDomDocument()
        self.styles = []
        self._load()

    def _load(self):
        with open(self.path, "rb") as fh:
            data = fh.read()
        try:
            self.doc.setContent(QByteArray(data))
        except Exception as exc:  # pragma: no cover
            raise ValueError("Could not parse the QLR file: {}".format(exc))
        root = self.doc.documentElement()
        if root.isNull():
            raise ValueError("The file is not a valid QLR (XML) file.")

        nodes = self.doc.elementsByTagName("maplayer")
        for i in range(nodes.count()):
            el = nodes.at(i).toElement()
            name = el.firstChildElement("layername").text().strip()
            if not name:
                continue
            ltype = el.attribute("type", "vector")
            kind = _qlr_geometry_kind(el) if ltype == "vector" else ""
            self.styles.append(QlrStyle(name, ltype, kind, el))
        if not self.styles:
            raise ValueError("No named layers were found in the QLR file.")

    def find_style(self, layer):
        """First QLR style matching by name and by type/geometry (topology)."""
        lname = _norm_name(layer.name())
        ltype = layer_type_key(layer)
        lkind = layer_geometry_kind(layer) if ltype == "vector" else ""
        for style in self.styles:
            if _norm_name(style.name) != lname or style.layer_type != ltype:
                continue
            if ltype == "vector" and style.kind not in ("unknown", lkind):
                continue
            return style
        return None


class ApplyResult:
    def __init__(self):
        self.applied = []          # "layer name (kind)"
        self.failed = []           # (layer name, error)
        self.unmatched_layers = [] # group layers with no style in the QLR
        self.unmatched_styles = [] # QLR styles that were used on nothing


def _layer_nodes(group, include_subgroups):
    if include_subgroups:
        return group.findLayers()
    # children() already yields typed nodes, so a plain isinstance check suffices
    return [child for child in group.children() if isinstance(child, QgsLayerTreeLayer)]


def collect_layers(groups, include_subgroups=True):
    """All distinct layers below the given group nodes (optionally recursive)."""
    layers, seen, broken = [], set(), []
    for group in groups:
        for node in _layer_nodes(group, include_subgroups):
            layer = node.layer()
            if layer is None:
                broken.append(node.name())
                continue
            if layer.id() in seen:
                continue
            seen.add(layer.id())
            layers.append(layer)
    return layers, broken


def _read_style(layer, element, context):
    """Call QgsMapLayer.readStyle across PyQGIS versions; returns (ok, error)."""
    try:
        # PyQGIS signature: readStyle(node, errorMessage, context, categories=All)
        res = layer.readStyle(element, "", context)
    except TypeError:
        res = layer.readStyle(element, context)
    if isinstance(res, tuple):
        return bool(res[0]), (res[1] if len(res) > 1 else "")
    return bool(res), ""


def apply_qlr_to_groups(qlr_path, groups, iface=None, include_subgroups=True):
    qlr = QlrFile(qlr_path)
    layers, broken = collect_layers(groups, include_subgroups)

    context = QgsReadWriteContext()
    context.setPathResolver(QgsPathResolver(qlr_path))

    result = ApplyResult()
    used = set()
    for name in broken:
        result.failed.append((name, "layer is not loaded / invalid"))

    for layer in layers:
        style = qlr.find_style(layer)
        if style is None:
            if layer_type_key(layer) != "other":
                result.unmatched_layers.append(layer.name())
            continue
        try:
            # Reads all style categories (symbology, labels, fields/forms, etc.)
            ok, err = _read_style(layer, style.element, context)
        except Exception as exc:
            ok, err = False, str(exc)
        if not ok:
            result.failed.append((layer.name(), err or "readStyle failed"))
            continue

        used.add(id(style))
        layer.triggerRepaint()
        try:
            layer.emitStyleChanged()
        except Exception:
            pass
        if iface is not None:
            try:
                iface.layerTreeView().refreshLayerSymbology(layer.id())
            except Exception:
                pass
        result.applied.append(style.label())

    result.unmatched_styles = [s.label() for s in qlr.styles if id(s) not in used]
    if result.applied:
        QgsProject.instance().setDirty(True)
    return result
