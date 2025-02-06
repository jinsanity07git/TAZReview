"""
my_app.py

Features:

1) 4 Panels:
   - Panel #1 (top-left): Old TAZ (not selectable) + block outlines in black dotted lines
   - Panel #2 (top-right): New TAZ (selectable) + same black dotted block outlines
       -> Selecting polygons here filters Panel #4 blocks to only those intersecting
          the selected New TAZ polygons.
   - Panel #3 (bottom-left): Combined (not selectable) with block outlines dotted
   - Panel #4 (bottom-right): Blocks (selectable) + black dotted boundary, and (by default)
       also filled with light color. If the user selects polygons in Panel #2,
       we re-filter the blocks to only those intersecting the selected New TAZ polygons.

2) A "Match 1st Panel Zoom" button that does a one-time sync of the zoom/pan
   from Panel #1 to Panels #2, #3, and #4 (no continuous linking).

3) On searching an Old TAZ ID, we initially filter both New TAZ and Blocks
   to those intersecting the Old TAZ. Then (optionally) further filter the
   Blocks by the selected New TAZ polygons.

4) Polygons are split at the sub-polygon level so each sub-polygon has its own
   row in the CDS, preventing KeyErrors when selecting sub-polygons.
"""

import geopandas as gpd
import shapely
from shapely.geometry import Polygon, MultiPolygon
import numpy as np

from bokeh.io import curdoc
from bokeh.layouts import column, row
from bokeh.models import (
    ColumnDataSource, DataTable, TableColumn,
    Div, TextInput, Button, Select, HoverTool, Range1d
)
from bokeh.plotting import figure
from bokeh.tile_providers import CARTODBPOSITRON, ESRI_IMAGERY, STAMEN_TONER, STAMEN_TERRAIN

# -------------------------------------------------------------------------
# 1. Load & Clean Shapefiles
# -------------------------------------------------------------------------
url_old_taz = r"./shapefiles/CTPS_TDM23_TAZ_2017g_v202303.shp"
url_new_taz = r"./shapefiles/taz_new_Jan14_1.shp"
url_blocks  = r"./shapefiles/blocks20a.shp"

gdf_old_taz  = gpd.read_file(url_old_taz)
gdf_new_taz  = gpd.read_file(url_new_taz)
gdf_blocks   = gpd.read_file(url_blocks)

def remove_zero_geoms(gdf):
    """Drop rows with geometry None/empty or bounding box == (0,0,0,0)."""
    def is_zero_bbox(geom):
        if geom is None or geom.is_empty:
            return True
        minx, miny, maxx, maxy = geom.bounds
        return (minx == 0 and miny == 0 and maxx == 0 and maxy == 0)
    return gdf[~gdf.geometry.apply(is_zero_bbox)].copy()

gdf_old_taz  = remove_zero_geoms(gdf_old_taz)
gdf_new_taz  = remove_zero_geoms(gdf_new_taz)
gdf_blocks   = remove_zero_geoms(gdf_blocks)

# -------------------------------------------------------------------------
# 2. Rename columns for consistency
# -------------------------------------------------------------------------
if 'taz_id' not in gdf_old_taz.columns:
    if 'TAZ_ID' in gdf_old_taz.columns:
        gdf_old_taz = gdf_old_taz.rename(columns={'TAZ_ID': 'taz_id'})

rename_map_new = {}
if 'taz_new1' in gdf_new_taz.columns:
    rename_map_new['taz_new1'] = 'taz_id'
if 'hh19' in gdf_new_taz.columns:
    rename_map_new['hh19']      = 'HH19'
if 'persns19' in gdf_new_taz.columns:
    rename_map_new['persns19']  = 'PERSNS19'
if 'workrs19' in gdf_new_taz.columns:
    rename_map_new['workrs19']  = 'WORKRS19'
if 'emp19' in gdf_new_taz.columns:
    rename_map_new['emp19']     = 'EMP19'
if rename_map_new:
    gdf_new_taz = gdf_new_taz.rename(columns=rename_map_new)

if 'GEOID20' in gdf_blocks.columns:
    gdf_blocks = gdf_blocks.rename(columns={'GEOID20': 'BLOCK_ID'})


# -------------------------------------------------------------------------
# 3. Helper Functions
# -------------------------------------------------------------------------
def latlon_to_web_mercator(gdf_in):
    """Convert a GeoDataFrame to EPSG:3857 for tile-based plotting."""
    return gdf_in.to_crs(epsg=3857)

def gdf_to_cds_polygons(gdf, id_field, ensure_cols=None):
    """
    Splits each MultiPolygon into multiple rows so that each sub-polygon is
    its own patch in the CDS. This prevents selection index errors in Bokeh.
    """
    if ensure_cols is None:
        ensure_cols = []

    # Ensure the columns exist
    for col in ensure_cols:
        if col not in gdf.columns:
            gdf[col] = None

    all_xs = []
    all_ys = []
    all_ids = []
    attr_lists = {col: [] for col in ensure_cols}

    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue

        row_id = str(row[id_field])
        row_attrs = {col: row[col] for col in ensure_cols}

        if geom.geom_type == "MultiPolygon":
            for subpoly in geom.geoms:
                xs, ys = subpoly.exterior.coords.xy
                all_xs.append(xs.tolist())
                all_ys.append(ys.tolist())
                all_ids.append(row_id)
                for c in ensure_cols:
                    attr_lists[c].append(row_attrs[c])
        elif geom.geom_type == "Polygon":
            xs, ys = geom.exterior.coords.xy
            all_xs.append(xs.tolist())
            all_ys.append(ys.tolist())
            all_ids.append(row_id)
            for c in ensure_cols:
                attr_lists[c].append(row_attrs[c])
        # skip other geometry types

    data = {'xs': all_xs, 'ys': all_ys, 'id': all_ids}
    for c in ensure_cols:
        data[c] = attr_lists[c]

    return ColumnDataSource(data=data)

def sum_columns(cds, columns):
    """Sum up numeric columns from a ColumnDataSource."""
    data = cds.data
    if not data or len(data.get('id', [])) == 0:
        return {c: 0 for c in columns}
    out = {}
    for c in columns:
        s = 0
        for val in data.get(c, []):
            if isinstance(val, (int,float)):
                s += val
        out[c] = s
    return out

def filter_old_taz_data(old_taz_id):
    """
    Filter Old TAZ, then find intersecting New TAZ + Blocks. Return
    (gdf_old_web, gdf_new_web, gdf_blocks_web).
    """
    subset_old = gdf_old_taz[gdf_old_taz['taz_id']==old_taz_id]
    if subset_old.empty:
        return (None, None, None)

    region = subset_old.unary_union
    subset_new    = gdf_new_taz[gdf_new_taz.intersects(region)]
    subset_blocks = gdf_blocks[gdf_blocks.intersects(region)]

    return (latlon_to_web_mercator(subset_old),
            latlon_to_web_mercator(subset_new),
            latlon_to_web_mercator(subset_blocks))

# -------------------------------------------------------------------------
# 4. DataSources for each panel
# -------------------------------------------------------------------------
old_taz_source        = ColumnDataSource(dict(xs=[], ys=[], id=[]))
old_taz_blocks_source = ColumnDataSource(dict(xs=[], ys=[], id=[]))

new_taz_source        = ColumnDataSource(dict(xs=[], ys=[], id=[], HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[]))
new_taz_blocks_source = ColumnDataSource(dict(xs=[], ys=[], id=[]))

combined_old_source    = ColumnDataSource(dict(xs=[], ys=[], id=[]))
combined_new_source    = ColumnDataSource(dict(xs=[], ys=[], id=[], HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[]))
combined_blocks_source = ColumnDataSource(dict(xs=[], ys=[], id=[]))

blocks_source = ColumnDataSource(dict(xs=[], ys=[], id=[], HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[]))

# We'll keep a reference to the "full blocks" after the Old TAZ filter (before
# further filtering by selected New TAZ polygons).
global_blocks_web = None

# -------------------------------------------------------------------------
# 5. Bokeh Figures
# -------------------------------------------------------------------------
TOOLS = "pan,wheel_zoom,box_zoom,reset"

p_old = figure(
    title="1) Old TAZ", width=400, height=300,
    match_aspect=True,
    x_axis_type="mercator", y_axis_type="mercator",
    tools=TOOLS, active_scroll='wheel_zoom'
)
p_new = figure(
    title="2) New TAZ", width=400, height=300,
    match_aspect=True,
    x_axis_type="mercator", y_axis_type="mercator",
    tools=TOOLS + ",tap", active_scroll='wheel_zoom'
)
p_combined = figure(
    title="3) Combined", width=400, height=300,
    match_aspect=True,
    x_axis_type="mercator", y_axis_type="mercator",
    tools=TOOLS, active_scroll='wheel_zoom'
)
p_blocks = figure(
    title="4) Blocks", width=400, height=300,
    match_aspect=True,
    x_axis_type="mercator", y_axis_type="mercator",
    tools=TOOLS + ",tap", active_scroll='wheel_zoom'
)

figs = [p_old, p_new, p_combined, p_blocks]
tile_refs = {}

def add_tile_providers():
    for f in figs:
        tile = f.add_tile(CARTODBPOSITRON)
        tile_refs[f] = tile

add_tile_providers()

# -------------------------------------------------------------------------
# 6. Patches (with black dotted lines for blocks in all panels)
# -------------------------------------------------------------------------
# Panel #1: Old TAZ
p_old.patches(
    xs="xs", ys="ys",
    source=old_taz_source,
    fill_color=None, line_color="green", line_width=2
)
# block outlines, black dotted
p_old.patches(
    xs="xs", ys="ys",
    source=old_taz_blocks_source,
    fill_color=None,
    line_color="black",
    line_width=2,
    line_dash='dotted'
)

# Panel #2: New TAZ
p_new.patches(
    xs="xs", ys="ys",
    source=new_taz_source,
    fill_color=None, line_color="red", line_width=2,
    selection_fill_color="yellow",
    selection_line_color="black",
    nonselection_fill_alpha=0.1,
    nonselection_fill_color="red"
)
# block outlines, black dotted
p_new.patches(
    xs="xs", ys="ys",
    source=new_taz_blocks_source,
    fill_color=None,
    line_color="black",
    line_width=2,
    line_dash='dotted'
)
p_new.add_tools(HoverTool(tooltips=[("New TAZ ID", "@id"), ("EMP19", "@EMP19")]))

# Panel #3: Combined
p_combined.patches(
    xs="xs", ys="ys",
    source=combined_blocks_source,
    fill_color=None,
    line_color="black",
    line_width=2,
    line_dash='dotted'
)
p_combined.patches(
    xs="xs", ys="ys",
    source=combined_old_source,
    fill_color=None, line_color="green", line_width=2
)
p_combined.patches(
    xs="xs", ys="ys",
    source=combined_new_source,
    fill_color=None, line_color="red", line_width=2
)

# Panel #4: Blocks
# We'll let blocks have a faint fill + black dotted boundary
p_blocks.patches(
    xs="xs", ys="ys",
    source=blocks_source,
    fill_color="#F9E79F", fill_alpha=0.5,
    line_color="black",
    line_width=2,
    line_dash='dotted',
    selection_fill_color="yellow",
    selection_line_color="red",
    nonselection_fill_alpha=0.3
)
p_blocks.add_tools(HoverTool(tooltips=[("Block ID", "@id"), ("EMP19", "@EMP19")]))

# -------------------------------------------------------------------------
# 7. Data Tables (New TAZ, Blocks)
# -------------------------------------------------------------------------
new_taz_table_source = ColumnDataSource(dict(id=[], HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[]))
blocks_table_source  = ColumnDataSource(dict(id=[], HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[]))

common_cols = [
    TableColumn(field="id",       title="ID"),
    TableColumn(field="HH19",     title="HH19"),
    TableColumn(field="PERSNS19", title="PERSNS19"),
    TableColumn(field="WORKRS19", title="WORKRS19"),
    TableColumn(field="EMP19",    title="EMP19"),
]
new_taz_data_table = DataTable(source=new_taz_table_source, columns=common_cols, width=400, height=200)
blocks_data_table  = DataTable(source=blocks_table_source,  columns=common_cols, width=400, height=200)

new_taz_sum_div = Div(text="Sum: HH19=0, PERSNS19=0, WORKRS19=0, EMP19=0")
blocks_sum_div  = Div(text="Sum: HH19=0, PERSNS19=0, WORKRS19=0, EMP19=0")

def new_taz_selection_change(attr, old, new):
    """
    Whenever the user selects polygons in the New TAZ panel (#2):
      1) Show them in the top data table + sums
      2) Further filter the blocks in Panel #4 to the union of selected polygons
         in New TAZ. This modifies blocks_source.
    """
    sel_inds = new_taz_source.selected.indices
    # 1) Update the "New TAZ Table"
    if not sel_inds:
        new_taz_table_source.data = dict(id=[], HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[])
        new_taz_sum_div.text = "Sum: HH19=0, PERSNS19=0, WORKRS19=0, EMP19=0"
        # Also reset blocks_source to the original blocks from the Old TAZ
        if global_blocks_web is not None:
            blocks_source.data = dict(gdf_to_cds_polygons(global_blocks_web, "BLOCK_ID",
                                      ["HH19","PERSNS19","WORKRS19","EMP19"]).data)
        return

    # Build a new data dict for the table
    d = {}
    for c in ["id","HH19","PERSNS19","WORKRS19","EMP19"]:
        d[c] = [new_taz_source.data[c][i] for i in sel_inds]
    new_taz_table_source.data = d

    sums = sum_columns(new_taz_table_source, ["HH19","PERSNS19","WORKRS19","EMP19"])
    new_taz_sum_div.text = (
        f"Sum: HH19={sums['HH19']}, "
        f"PERSNS19={sums['PERSNS19']}, "
        f"WORKRS19={sums['WORKRS19']}, "
        f"EMP19={sums['EMP19']}"
    )

    # 2) Intersect blocks with the selected New TAZ polygons
    # We'll gather the geometry of each selected polygon from new_taz_source
    # Then unify them, then filter "global_blocks_web" to blocks that intersect.
    if global_blocks_web is None:
        return

    # Reconstruct the selected polygons from new_taz_source
    # We need to know that each row is its own geometry. We'll track them in parallel with an index array.
    selected_geom_list = []
    for i in sel_inds:
        # i is the row in the CDS, we must somehow map it back to geometry
        # But we've splitted multipolygons. So let's store them in a separate structure:
        pass

    # Instead of reconstructing from the CDS, let's store the actual gdf of new_web in memory
    # for the entire set, then we check sub-polygons. We can do a simpler approach:
    # We'll keep a "global_new_web" too, and each row in the CDS maps 1 subpoly => we have a custom list
    # for geometry. But that can get complicated quickly. Alternatively, we can "approx" by ID and filter.

    # **Simpler Approach**: We assume each sub-polygon in new_taz_source has the same "id" as the TAZ.
    # If multiple sub-polygons share the same TAZ, selecting any sub-polygon means selecting that TAZ ID.
    # We'll gather the set of TAZ IDs from the selection => unify them from the global_new_web geometry.

    # So let's gather the TAZ IDs from the selection:
    sel_ids = set(new_taz_source.data['id'][i] for i in sel_inds)
    # Then from the global_new_web (which we stored?), unify them.
    # We'll store the "global_new_web" gdf too:

    # We'll do it in 2 steps:
    pass

def blocks_selection_change(attr, old, new):
    """
    When user selects blocks in Panel #4 => show them in the bottom table + sums
    (No additional filtering logic here).
    """
    sel_inds = blocks_source.selected.indices
    if not sel_inds:
        blocks_table_source.data = dict(id=[], HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[])
        blocks_sum_div.text = "Sum: HH19=0, PERSNS19=0, WORKRS19=0, EMP19=0"
        return

    d = {}
    for c in ["id","HH19","PERSNS19","WORKRS19","EMP19"]:
        d[c] = [blocks_source.data[c][i] for i in sel_inds]
    blocks_table_source.data = d

    sums = sum_columns(blocks_table_source, ["HH19","PERSNS19","WORKRS19","EMP19"])
    blocks_sum_div.text = (
        f"Sum: HH19={sums['HH19']}, "
        f"PERSNS19={sums['PERSNS19']}, "
        f"WORKRS19={sums['WORKRS19']}, "
        f"EMP19={sums['EMP19']}"
    )

new_taz_source.selected.on_change("indices", new_taz_selection_change)
blocks_source.selected.on_change("indices", blocks_selection_change)

# We also want to store "global_new_web" and "global_blocks_web" so that we can do the intersection
# in the new_taz_selection_change callback. Let's define them as module-level:
global_new_web = None
global_blocks_web = None

def do_new_taz_selection_intersection():
    """
    Actually do the intersection of the selected TAZ polygons with the blocks,
    then update 'blocks_source'.
    """
    import shapely.ops

    sel_inds = new_taz_source.selected.indices
    if not sel_inds or global_new_web is None or global_blocks_web is None:
        return

    # Gather the unique TAZ IDs from the selection
    sel_ids = set(new_taz_source.data['id'][i] for i in sel_inds)
    if not sel_ids:
        return

    # Filter global_new_web to those TAZs, then unify geometry
    chosen_taz_gdf = global_new_web[global_new_web['taz_id'].astype(str).isin(sel_ids)]
    if chosen_taz_gdf.empty:
        return

    union_poly = chosen_taz_gdf.unary_union

    # Now filter the blocks from global_blocks_web to those intersecting union_poly
    filtered_blocks = global_blocks_web[global_blocks_web.intersects(union_poly)]
    # Convert to a CDS
    new_blocks_cds = gdf_to_cds_polygons(filtered_blocks, "BLOCK_ID",
                        ensure_cols=["HH19","PERSNS19","WORKRS19","EMP19"])
    blocks_source.data = dict(new_blocks_cds.data)

def new_taz_selection_change(attr, old, new):
    """
    Updated version that:
      1) Updates the top table
      2) Actually re-filters blocks by intersection with selected TAZ polygons
    """
    sel_inds = new_taz_source.selected.indices
    # 1) Table
    if not sel_inds:
        new_taz_table_source.data = dict(id=[], HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[])
        new_taz_sum_div.text = "Sum: HH19=0, PERSNS19=0, WORKRS19=0, EMP19=0"
        # If no selection => revert blocks to all blocks from global_blocks_web
        if global_blocks_web is not None:
            blocks_source.data = dict(
                gdf_to_cds_polygons(global_blocks_web, "BLOCK_ID",
                                    ["HH19","PERSNS19","WORKRS19","EMP19"]).data
            )
        return

    d = {}
    for c in ["id","HH19","PERSNS19","WORKRS19","EMP19"]:
        d[c] = [new_taz_source.data[c][i] for i in sel_inds]
    new_taz_table_source.data = d

    sums = sum_columns(new_taz_table_source, ["HH19","PERSNS19","WORKRS19","EMP19"])
    new_taz_sum_div.text = (
        f"Sum: HH19={sums['HH19']}, "
        f"PERSNS19={sums['PERSNS19']}, "
        f"WORKRS19={sums['WORKRS19']}, "
        f"EMP19={sums['EMP19']}"
    )

    # 2) Re-filter blocks
    do_new_taz_selection_intersection()


# -------------------------------------------------------------------------
# 8. UI Elements
# -------------------------------------------------------------------------
text_input     = TextInput(value="", title="Enter Old TAZ ID:")
search_button  = Button(label="Search TAZ", button_type="success")
search_status  = Div(text="<b>Currently searching TAZ:</b> (none)")

match_zoom_button = Button(label="Match 1st Panel Zoom", button_type="default")

tile_select = Select(
    title="Map Type",
    value="CartoDB Positron",
    options=["CartoDB Positron","ESRI Satellite","Stamen Toner","Stamen Terrain"]
)

def set_tile_provider(fig, provider):
    old_tile = tile_refs.get(fig)
    if old_tile and old_tile in fig.renderers:
        fig.renderers.remove(old_tile)
    new_tile = fig.add_tile(provider)
    tile_refs[fig] = new_tile

def on_tile_select_change(attr, old, new):
    if new == "CartoDB Positron":
        provider = CARTODBPOSITRON
    elif new == "ESRI Satellite":
        provider = ESRI_IMAGERY
    elif new == "Stamen Toner":
        provider = STAMEN_TONER
    elif new == "Stamen Terrain":
        provider = STAMEN_TERRAIN
    else:
        provider = CARTODBPOSITRON
    for f in figs:
        set_tile_provider(f, provider)

tile_select.on_change("value", on_tile_select_change)


def on_search_click():
    search_status.text = "<b>Currently searching TAZ:</b> loading..."
    # Clear selections
    new_taz_source.selected.update(indices=[])
    blocks_source.selected.update(indices=[])
    # Parse input
    val = text_input.value.strip()
    if not val:
        search_status.text = "<b>Currently searching TAZ:</b> (no input)"
        return
    try:
        old_id_int = int(val)
    except ValueError:
        search_status.text = f"<b>Currently searching TAZ:</b> invalid '{val}'"
        return

    old_web, new_web, blocks_web = filter_old_taz_data(old_id_int)
    if old_web is None or old_web.empty:
        search_status.text = f"<b>Currently searching TAZ:</b> TAZ {old_id_int} not found"
        return

    # Store references so we can do further intersection in new_taz_selection_change
    global global_new_web
    global global_blocks_web
    global_new_web = new_web
    global_blocks_web = blocks_web

    # Convert to CDS
    old_temp          = gdf_to_cds_polygons(old_web,    "taz_id")
    old_blocks_temp   = gdf_to_cds_polygons(blocks_web, "BLOCK_ID")

    new_temp          = gdf_to_cds_polygons(new_web,    "taz_id",
                          ensure_cols=["HH19","PERSNS19","WORKRS19","EMP19"])
    new_blocks_temp   = gdf_to_cds_polygons(blocks_web, "BLOCK_ID")

    comb_old_temp     = old_temp
    comb_new_temp     = new_temp
    comb_blocks_temp  = gdf_to_cds_polygons(blocks_web, "BLOCK_ID")

    blocks_temp       = gdf_to_cds_polygons(blocks_web, "BLOCK_ID",
                          ensure_cols=["HH19","PERSNS19","WORKRS19","EMP19"])

    old_taz_source.data         = dict(old_temp.data)
    old_taz_blocks_source.data  = dict(old_blocks_temp.data)
    new_taz_source.data         = dict(new_temp.data)
    new_taz_blocks_source.data  = dict(new_blocks_temp.data)
    combined_old_source.data    = dict(comb_old_temp.data)
    combined_new_source.data    = dict(comb_new_temp.data)
    combined_blocks_source.data = dict(comb_blocks_temp.data)
    blocks_source.data          = dict(blocks_temp.data)

    search_status.text = f"<b>Currently searching TAZ:</b> {old_id_int}"

    # Zoom to bounding box of old_taz
    minx, miny, maxx, maxy = old_web.total_bounds
    if minx == maxx or miny == maxy:
        minx -= 1000
        maxx += 1000
        miny -= 1000
        maxy += 1000
    else:
        dx = maxx - minx
        dy = maxy - miny
        minx -= 0.05 * dx
        maxx += 0.05 * dx
        miny -= 0.05 * dy
        maxy += 0.05 * dy

    p_old.x_range.start = minx
    p_old.x_range.end   = maxx
    p_old.y_range.start = miny
    p_old.y_range.end   = maxy

search_button.on_click(on_search_click)

def on_match_zoom_click():
    """
    When pressed, set panels #2, #3, #4 to the same numeric x_range/y_range as #1.
    (One-time, no continuous linking.)
    """
    p_new.x_range.start      = p_old.x_range.start
    p_new.x_range.end        = p_old.x_range.end
    p_new.y_range.start      = p_old.y_range.start
    p_new.y_range.end        = p_old.y_range.end

    p_combined.x_range.start = p_old.x_range.start
    p_combined.x_range.end   = p_old.x_range.end
    p_combined.y_range.start = p_old.y_range.start
    p_combined.y_range.end   = p_old.y_range.end

    p_blocks.x_range.start   = p_old.x_range.start
    p_blocks.x_range.end     = p_old.x_range.end
    p_blocks.y_range.start   = p_old.y_range.start
    p_blocks.y_range.end     = p_old.y_range.end

match_zoom_button.on_click(on_match_zoom_click)

# -------------------------------------------------------------------------
# 9. Layout
# -------------------------------------------------------------------------
# Right side => 2 tables, one for New TAZ, one for Blocks
new_taz_table_layout = column(
    Div(text="<b>New TAZ Table</b> (Panel #2 Selection)"),
    new_taz_data_table,
    new_taz_sum_div
)
blocks_table_layout = column(
    Div(text="<b>Blocks Table</b> (Panel #4 Selection)"),
    blocks_data_table,
    blocks_sum_div
)
tables_right = column(
    new_taz_table_layout,
    blocks_table_layout,
    width=400
)

# Left side => 4 panels in a 2x2
maps_layout = column(
    row(p_old,      p_new,      sizing_mode="stretch_both"),
    row(p_combined, p_blocks,   sizing_mode="stretch_both"),
    sizing_mode="stretch_both"
)

top_controls = row(text_input, search_button, match_zoom_button, tile_select)
layout_final = column(
    top_controls,
    search_status,
    row(maps_layout, tables_right, sizing_mode="stretch_both"),
    sizing_mode="stretch_both"
)

curdoc().add_root(layout_final)
curdoc().title = "4-Panel TAZ with Block Intersection & Single-Click Zoom Sync"
