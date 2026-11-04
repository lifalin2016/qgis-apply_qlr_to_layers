# Apply QLR to layers (QGIS 3.22+ and 4.x)

Right-click a layer group -> **Apply QLR file to layers** -> choose a `.qlr` file and
whether layers in subgroups should be included (checkbox, on by default).

* Every named layer in the QLR is read.
* Each layer in the group (including sub-groups) is matched against the QLR by
  **name** and **geometry type** (point / line / polygon; for non-vector layers by layer type).
* The matching style (all style categories) overwrites the layer's existing style.
* A summary lists what was applied and what matched nothing.

Install: copy the folder `apply_qlr_to_layers` into your QGIS profile's `python/plugins`
directory (or use *Plugins > Manage and Install Plugins > Install from ZIP*), then enable it.

* Optional (on by default): the layer's **preview expression** is copied from the QLR as well.
  Layers whose QLR entry has no preview expression keep their current one.
