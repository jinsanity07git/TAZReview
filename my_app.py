"""
my_app.py

Implements:
1) A ~3/4 (maps) and ~1/4 (tables) layout that scales with browser resizing.
2) Only two tile providers: CartoDB Positron (default) and ESRI Satellite.
3) Blocks are intersected with the *union of New TAZ polygons* (not Old TAZ directly).
4) The "Match 1st Panel Zoom" button is a one‐time sync, no continuous linking.
5) Consolidated view has blocks in a yellowish transparent hue.
"""

import geopandas as gpd
from shapely.geometry import Polygon, MultiPolygon
import numpy as np

from bokeh.io import curdoc
from bokeh.layouts import column, row
from bokeh.models import (
    ColumnDataSource, DataTable, TableColumn, 
    Div, TextInput, Button, Select, HoverTool, Range1d
)
from bokeh.plotting import figure
# We only keep CartoDB and ESRI
from bokeh.tile_providers import CARTODBPOSITRON, ESRI_IMAGERY

# -------------------------------------------------------------------------
# 1. Load & Rename Shapefiles
# -------------------------------------------------------------------------
url_old_taz = r"./shapefiles/CTPS_TDM23_TAZ_2017g_v202303.shp"
url_new_taz = r"./shapefiles/taz_new_Jan14_1.shp"
url_blocks  = r"./shapefiles/blocks20a.shp"

gdf_old_taz  = gpd.read_file(url_old_taz)
gdf_new_taz  = gpd.read_file(url_new_taz)
gdf_blocks   = gpd.read_file(url_blocks)


def remove_zero_geoms(gdf):
    """Remove geometry if it's empty or bounding box is (0,0,0,0)."""
    def is_zero_bbox(geom):
        if geom is None or geom.is_empty:
            return True
        minx, miny, maxx, maxy = geom.bounds
        return (minx == 0 and miny == 0 and maxx == 0 and maxy == 0)
    return gdf[~gdf.geometry.apply(is_zero_bbox)].copy()

gdf_old_taz  = remove_zero_geoms(gdf_old_taz)
gdf_new_taz  = remove_zero_geoms(gdf_new_taz)
gdf_blocks   = remove_zero_geoms(gdf_blocks)

# Standardize columns
if 'taz_id' not in gdf_old_taz.columns:
    if 'TAZ_ID' in gdf_old_taz.columns:
        gdf_old_taz = gdf_old_taz.rename(columns={'TAZ_ID':'taz_id'})
rename_map_new = {}
if 'taz_new1' in gdf_new_taz.columns:
    rename_map_new['taz_new1'] = 'taz_id'
if 'hh19' in gdf_new_taz.columns:
    rename_map_new['hh19'] = 'HH19'
if 'persns19' in gdf_new_taz.columns:
    rename_map_new['persns19'] = 'PERSNS19'
if 'workrs19' in gdf_new_taz.columns:
    rename_map_new['workrs19'] = 'WORKRS19'
if 'emp19' in gdf_new_taz.columns:
    rename_map_new['emp19'] = 'EMP19'

if rename_map_new:
    gdf_new_taz = gdf_new_taz.rename(columns=rename_map_new)

if 'GEOID20' in gdf_blocks.columns:
    gdf_blocks = gdf_blocks.rename(columns={'GEOID20':'BLOCK_ID'})


# -------------------------------------------------------------------------
# 2. Helper Functions
# -------------------------------------------------------------------------
def latlon_to_web_mercator(gdf):
    """Convert a GeoDataFrame to EPSG:3857 for tile-based plotting."""
    return gdf.to_crs(epsg=3857)

def split_multipolygons_to_cds(gdf, id_field, ensure_cols=None):
    """
    Each sub-polygon in a MultiPolygon becomes a separate row in the CDS
    so that Bokeh selection is per-sub-polygon (avoiding index mismatch).
    """
    from bokeh.models import ColumnDataSource
    if ensure_cols is None:
        ensure_cols = []

    # Ensure columns exist
    for c in ensure_cols:
        if c not in gdf.columns:
            gdf[c] = None

    all_xs = []
    all_ys = []
    all_ids = []
    attr_data = {c: [] for c in ensure_cols}

    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        
        row_id = str(row[id_field])
        row_attrs = {c: row[c] for c in ensure_cols}

        if geom.geom_type == "MultiPolygon":
            for subpoly in geom.geoms:
                xs, ys = subpoly.exterior.coords.xy
                all_xs.append(xs.tolist())
                all_ys.append(ys.tolist())
                all_ids.append(row_id)
                for c in ensure_cols:
                    attr_data[c].append(row_attrs[c])
        elif geom.geom_type == "Polygon":
            xs, ys = geom.exterior.coords.xy
            all_xs.append(xs.tolist())
            all_ys.append(ys.tolist())
            all_ids.append(row_id)
            for c in ensure_cols:
                attr_data[c].append(row_attrs[c])

    data = {
        'xs': all_xs,
        'ys': all_ys,
        'id': all_ids
    }
    for c in ensure_cols:
        data[c] = attr_data[c]
    return ColumnDataSource(data)

def sum_columns(cds, columns):
    """
    Return a dict of {col: sum_of_col} ignoring non-numeric entries.
    """
    data = cds.data
    if not data or len(data.get('id', [])) == 0:
        return {c: 0 for c in columns}
    out = {}
    for c in columns:
        s = 0
        for val in data.get(c, []):
            if isinstance(val, (int, float)):
                s += val
        out[c] = s
    return out

# -------------------------------------------------------------------------
# 3. The Filtering Logic
# -------------------------------------------------------------------------
# 3a. Filter Old TAZ
def filter_old_taz(old_taz_id):
    """
    1) Find old TAZ geometry.
    2) Filter new TAZ to intersect that geometry => new_web
    3) Filter blocks to intersect the union of those new TAZ polygons => blocks_web
       (So blocks are only those intersecting the new TAZ region.)
    """
    subset_old = gdf_old_taz[gdf_old_taz['taz_id']==old_taz_id]
    if subset_old.empty:
        return (None, None, None)
    old_union = subset_old.unary_union

    # Filter new TAZ by old_union
    new_sub = gdf_new_taz[gdf_new_taz.intersects(old_union)]
    if new_sub.empty:
        return (subset_old, None, None)

    new_union = new_sub.unary_union

    # Blocks that intersect the union of new TAZ polygons
    blocks_sub = gdf_blocks[gdf_blocks.intersects(new_union)]

    return (subset_old, new_sub, blocks_sub)

# -------------------------------------------------------------------------
# 4. DataSources for the 4 panels
# -------------------------------------------------------------------------
from bokeh.models import ColumnDataSource

old_taz_source        = ColumnDataSource(dict(xs=[], ys=[], id=[]))
new_taz_source        = ColumnDataSource(dict(xs=[], ys=[], id=[], HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[]))
combined_old_source   = ColumnDataSource(dict(xs=[], ys=[], id=[]))
combined_new_source   = ColumnDataSource(dict(xs=[], ys=[], id=[], HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[]))
blocks_source         = ColumnDataSource(dict(xs=[], ys=[], id=[], HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[]))
old_taz_blocks_source = ColumnDataSource(dict(xs=[], ys=[], id=[]))
new_taz_blocks_source = ColumnDataSource(dict(xs=[], ys=[], id=[]))
combined_blocks_source= ColumnDataSource(dict(xs=[], ys=[], id=[]))

# We also store references to the "raw" GeoDataFrames in memory (web-mercator form)
global_old_web = None
global_new_web = None
global_blocks_web = None

# -------------------------------------------------------------------------
# 5. Figures
# -------------------------------------------------------------------------
TOOLS = "pan,wheel_zoom,box_zoom,reset"

p_old = figure(
    title="1) Old TAZ", 
    match_aspect=True,
    x_axis_type="mercator", y_axis_type="mercator",
    tools=TOOLS, active_scroll='wheel_zoom',
    sizing_mode="stretch_both",
    height=400
)
p_new = figure(
    title="2) New TAZ", 
    match_aspect=True,
    x_axis_type="mercator", y_axis_type="mercator",
    tools=TOOLS + ",tap", active_scroll='wheel_zoom',
    sizing_mode="stretch_both",
    height=400
)
p_combined = figure(
    title="3) Consolidated", 
    match_aspect=True,
    x_axis_type="mercator", y_axis_type="mercator",
    tools=TOOLS, active_scroll='wheel_zoom',
    sizing_mode="stretch_both",
    height=400
)
p_blocks = figure(
    title="4) Blocks", 
    match_aspect=True,
    x_axis_type="mercator", y_axis_type="mercator",
    tools=TOOLS + ",tap", active_scroll='wheel_zoom',
    sizing_mode="stretch_both",
    height=400
)

figs = [p_old, p_new, p_combined, p_blocks]
tile_map = {}

def setup_tiles():
    # Use CartoDB as default
    for f in figs:
        tile = f.add_tile(CARTODBPOSITRON)
        tile_map[f] = tile

setup_tiles()

# -------------------------------------------------------------------------
# 6. Add the Patches
# -------------------------------------------------------------------------
# Panel #1: Old TAZ + blocks dotted
p_old.patches(
    xs="xs", ys="ys",
    source=old_taz_source,
    fill_color=None,
    line_color="green",
    line_width=2
)
p_old.patches(
    xs="xs", ys="ys",
    source=old_taz_blocks_source,
    fill_color=None,
    line_color="black",
    line_width=2,
    line_dash="dotted"
)

# Panel #2: New TAZ + blocks dotted
p_new.patches(
    xs="xs", ys="ys",
    source=new_taz_source,
    fill_color=None,
    line_color="red",
    line_width=2,
    selection_fill_color="yellow",
    selection_line_color="black",
    nonselection_fill_alpha=0.1,
    nonselection_fill_color="red"
)
p_new.patches(
    xs="xs", ys="ys",
    source=new_taz_blocks_source,
    fill_color=None,
    line_color="black",
    line_width=2,
    line_dash="dotted"
)
p_new.add_tools(HoverTool(tooltips=[("TAZ ID","@id"),("EMP19","@EMP19")]))

# Panel #3: Combined, with blocks as a "yellowish transparent hue"
p_combined.patches(
    xs="xs", ys="ys",
    source=combined_blocks_source,
    fill_color="#FFFF80",  # pale yellow
    fill_alpha=0.4,
    line_color="black",
    line_width=2,
    line_dash="dotted"
)
p_combined.patches(
    xs="xs", ys="ys",
    source=combined_old_source,
    fill_color=None,
    line_color="green",
    line_width=2
)
p_combined.patches(
    xs="xs", ys="ys",
    source=combined_new_source,
    fill_color=None,
    line_color="red",
    line_width=2
)

# Panel #4: Blocks, selectable
p_blocks.patches(
    xs="xs", ys="ys",
    source=blocks_source,
    fill_color="#F9E79F",
    fill_alpha=0.5,
    line_color="black",
    line_width=2,
    line_dash="dotted",
    selection_fill_color="yellow",
    selection_line_color="red",
    nonselection_fill_alpha=0.3
)

# -------------------------------------------------------------------------
# 7. Tables for "New TAZ" (top) & "Blocks" (bottom)
# -------------------------------------------------------------------------
new_taz_table_source = ColumnDataSource(dict(id=[],HH19=[],PERSNS19=[],WORKRS19=[],EMP19=[]))
blocks_table_source  = ColumnDataSource(dict(id=[],HH19=[],PERSNS19=[],WORKRS19=[],EMP19=[]))

common_cols = [
    TableColumn(field="id",       title="ID"),
    TableColumn(field="HH19",     title="HH19"),
    TableColumn(field="PERSNS19", title="PERSNS19"),
    TableColumn(field="WORKRS19", title="WORKRS19"),
    TableColumn(field="EMP19",    title="EMP19"),
]
new_taz_data_table = DataTable(source=new_taz_table_source, columns=common_cols, width=350, height=200)
blocks_data_table  = DataTable(source=blocks_table_source,  columns=common_cols, width=350, height=200)

new_taz_sum_div = Div(text="Sum: HH19=0, PERSNS19=0, WORKRS19=0, EMP19=0")
blocks_sum_div  = Div(text="Sum: HH19=0, PERSNS19=0, WORKRS19=0, EMP19=0")

def new_taz_selection_change(attr, old, new):
    """
    Update the top table from the selection in Panel #2.
    """
    inds = new_taz_source.selected.indices
    if not inds:
        # Clear top table
        new_taz_table_source.data = dict(id=[],HH19=[],PERSNS19=[],WORKRS19=[],EMP19=[])
        new_taz_sum_div.text = "Sum: HH19=0, PERSNS19=0, WORKRS19=0, EMP19=0"
        return
    d = {}
    for c in ["id","HH19","PERSNS19","WORKRS19","EMP19"]:
        d[c] = [ new_taz_source.data[c][i] for i in inds ]
    new_taz_table_source.data = d

    sums = sum_columns(new_taz_table_source, ["HH19","PERSNS19","WORKRS19","EMP19"])
    new_taz_sum_div.text = (f"Sum: HH19={sums['HH19']}, "
                            f"PERSNS19={sums['PERSNS19']}, "
                            f"WORKRS19={sums['WORKRS19']}, "
                            f"EMP19={sums['EMP19']}")

new_taz_source.selected.on_change("indices", new_taz_selection_change)

def blocks_selection_change(attr, old, new):
    """
    Update the bottom table from the selection in Panel #4.
    """
    inds = blocks_source.selected.indices
    if not inds:
        blocks_table_source.data = dict(id=[],HH19=[],PERSNS19=[],WORKRS19=[],EMP19=[])
        blocks_sum_div.text = "Sum: HH19=0, PERSNS19=0, WORKRS19=0, EMP19=0"
        return
    d = {}
    for c in ["id","HH19","PERSNS19","WORKRS19","EMP19"]:
        d[c] = [ blocks_source.data[c][i] for i in inds ]
    blocks_table_source.data = d

    sums = sum_columns(blocks_table_source, ["HH19","PERSNS19","WORKRS19","EMP19"])
    blocks_sum_div.text = (f"Sum: HH19={sums['HH19']}, "
                           f"PERSNS19={sums['PERSNS19']}, "
                           f"WORKRS19={sums['WORKRS19']}, "
                           f"EMP19={sums['EMP19']}")

blocks_source.selected.on_change("indices", blocks_selection_change)

# -------------------------------------------------------------------------
# 8. Controls
# -------------------------------------------------------------------------
text_input = TextInput(value="", title="Enter Old TAZ ID:")
search_button = Button(label="Search TAZ", button_type="success")
match_zoom_button = Button(label="Match 1st Panel Zoom", button_type="default")

tile_select = Select(
    title="Map Type",
    value="CartoDB Positron",
    options=["CartoDB Positron","ESRI Satellite"]
)

search_status = Div(text="<b>Currently searching TAZ:</b> (none)")

def set_tile_provider(fig, provider):
    old = tile_map.get(fig)
    if old and old in fig.renderers:
        fig.renderers.remove(old)
    newtile = fig.add_tile(provider)
    tile_map[fig] = newtile

def on_tile_change(attr, old, new):
    if new == "CartoDB Positron":
        provider = CARTODBPOSITRON
    else:
        provider = ESRI_IMAGERY  # only two options
    for f in figs:
        set_tile_provider(f, provider)

tile_select.on_change("value", on_tile_change)


def on_search_click():
    """
    1) Filter old TAZ by user input
    2) Then find new TAZ that intersects
    3) Then find blocks that intersect the union of that new TAZ
    4) Convert to ColumnDataSource
    5) Zoom panel #1
    """
    search_status.text = "<b>Currently searching TAZ:</b> ...loading..."
    val = text_input.value.strip()
    if not val:
        search_status.text = "<b>Currently searching TAZ:</b> (no input)"
        return
    try:
        old_id_int = int(val)
    except ValueError:
        search_status.text = f"<b>Currently searching TAZ:</b> invalid '{val}'"
        return

    old_gdf, new_gdf, blocks_gdf = filter_old_taz(old_id_int)
    if old_gdf is None or old_gdf.empty:
        search_status.text = f"<b>Currently searching TAZ:</b> not found: {old_id_int}"
        return
    search_status.text = f"<b>Currently searching TAZ:</b> {old_id_int}"

    # Convert each to Web Mercator
    global global_old_web, global_new_web, global_blocks_web
    global_old_web    = latlon_to_web_mercator(old_gdf)
    global_new_web    = latlon_to_web_mercator(new_gdf)  if new_gdf    is not None else None
    global_blocks_web = latlon_to_web_mercator(blocks_gdf) if blocks_gdf is not None else None

    old_temp = split_multipolygons_to_cds(global_old_web, "taz_id")
    new_temp = (split_multipolygons_to_cds(global_new_web, "taz_id",
                ["HH19","PERSNS19","WORKRS19","EMP19"]) if global_new_web is not None else ColumnDataSource())
    blocks_temp = (split_multipolygons_to_cds(global_blocks_web, "BLOCK_ID",
                  ["HH19","PERSNS19","WORKRS19","EMP19"]) if global_blocks_web is not None else ColumnDataSource())

    # For dotted blocks in panel #1, #2, #3
    old_blocks_temp = split_multipolygons_to_cds(global_blocks_web, "BLOCK_ID") if global_blocks_web is not None else ColumnDataSource()
    new_blocks_temp = split_multipolygons_to_cds(global_blocks_web, "BLOCK_ID") if global_blocks_web is not None else ColumnDataSource()

    # Combined: old + new + blocks
    comb_old_temp = old_temp
    comb_new_temp = new_temp
    comb_blocks_temp = split_multipolygons_to_cds(global_blocks_web, "BLOCK_ID") if global_blocks_web is not None else ColumnDataSource()

    # Update data sources
    old_taz_source.data         = dict(old_temp.data)
    new_taz_source.data         = dict(new_temp.data)
    blocks_source.data          = dict(blocks_temp.data)
    old_taz_blocks_source.data  = dict(old_blocks_temp.data)
    new_taz_blocks_source.data  = dict(new_blocks_temp.data)
    combined_old_source.data    = dict(comb_old_temp.data)
    combined_new_source.data    = dict(comb_new_temp.data)
    combined_blocks_source.data = dict(comb_blocks_temp.data)

    # Clear any selection
    new_taz_source.selected.indices = []
    blocks_source.selected.indices  = []

    # Zoom panel #1 to bounding box
    bounds = global_old_web.total_bounds  # [minx, miny, maxx, maxy]
    minx, miny, maxx, maxy = bounds
    if minx == maxx or miny == maxy:
        minx -= 1000
        maxx += 1000
        miny -= 1000
        maxy += 1000
    else:
        dx = maxx - minx
        dy = maxy - miny
        minx -= 0.05*dx
        maxx += 0.05*dx
        miny -= 0.05*dy
        maxy += 0.05*dy

    p_old.x_range.start = minx
    p_old.x_range.end   = maxx
    p_old.y_range.start = miny
    p_old.y_range.end   = maxy

search_button.on_click(on_search_click)

def on_match_zoom_click():
    """
    One‐time setting of panels #2, #3, #4 to the same numeric x_range/y_range
    as panel #1. No continuous linking after that.
    """
    p_new.x_range.start = p_old.x_range.start
    p_new.x_range.end   = p_old.x_range.end
    p_new.y_range.start = p_old.y_range.start
    p_new.y_range.end   = p_old.y_range.end

    p_combined.x_range.start = p_old.x_range.start
    p_combined.x_range.end   = p_old.x_range.end
    p_combined.y_range.start = p_old.y_range.start
    p_combined.y_range.end   = p_old.y_range.end

    p_blocks.x_range.start = p_old.x_range.start
    p_blocks.x_range.end   = p_old.x_range.end
    p_blocks.y_range.start = p_old.y_range.start
    p_blocks.y_range.end   = p_old.y_range.end

match_zoom_button.on_click(on_match_zoom_click)


# -------------------------------------------------------------------------
# 9. Layout
# -------------------------------------------------------------------------
# 9a. The tables on the right, ~1/4 the width
new_taz_table_layout = column(
    Div(text="<b>New TAZ Table</b> (Panel #2 selection)"),
    new_taz_data_table,
    new_taz_sum_div
)
blocks_table_layout = column(
    Div(text="<b>Blocks Table</b> (Panel #4 selection)"),
    blocks_data_table,
    blocks_sum_div
)
tables_col = column(
    new_taz_table_layout,
    blocks_table_layout,
    width=350,  # ~1/4 of typical screen
    sizing_mode="fixed"  # or 'stretch_height'
)

# 9b. The 4 panels (2 rows, 2 columns) => ~3/4 of width
top_row = row(p_old, p_new, sizing_mode="stretch_both")
bottom_row = row(p_combined, p_blocks, sizing_mode="stretch_both")
maps_col = column(
    top_row,
    bottom_row,
    sizing_mode="stretch_both"
)

# 9c. The row combining maps_col (~3/4) and tables_col (~1/4)
main_row = row(
    maps_col,
    tables_col,
    sizing_mode="stretch_both"
)

# 9d. The top controls
top_controls = row(
    text_input,
    search_button,
    match_zoom_button,
    tile_select,
    sizing_mode="stretch_width"
)

layout_final = column(
    top_controls,
    search_status,
    main_row,
    sizing_mode="stretch_both"
)

curdoc().add_root(layout_final)
curdoc().title = "4-Panel TAZ (Blocks intersect New TAZ), ~3/4 : ~1/4 Layout"
