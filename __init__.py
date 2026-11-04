def classFactory(iface):
    from .plugin import ApplyQlrToLayersPlugin
    return ApplyQlrToLayersPlugin(iface)
