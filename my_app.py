"""
my_app.py

Usage:
    bokeh serve --show my_app.py

Implements:
 - Old TAZ search (only the directly intersecting New TAZ & Blocks).
 - "Loading..." indicator during search.
 - A "Match Old TAZ Zoom" toggle that makes the other 3 panels share the same
   x_range/y_range as the Old TAZ panel.
 - Scroll zoom enabled.
 - Table layout on the right ~1/4 width, maps on the left ~3/4 width.
"""

import geopandas as gpd
from shapely.geometry import Polygon, MultiPolygon
import numpy as np

from bokeh.io import curdoc
from bokeh.layouts import column, row
from bokeh.models import (
    ColumnDataSource, DataTable, TableColumn,
    Div, TextInput, Button, Toggle, Select,
    HoverTool, Range1d
)
from bokeh.plotting import figure
# Bokeh 3.x: tile_providers is deprecated but still works in 3.4.x
from bokeh.tile_providers import CARTODBPOSITRON, ESRI_IMAGERY, STAMEN_TONER, STAMEN_TERRAIN

# -------------------------------------------------------------------------
# 1. Load Shapefiles
# -------------------------------------------------------------------------
url_old_taz = r"./shapefiles/CTPS_TDM23_TAZ_2017g_v202303.shp"
url_new_taz = r"./shapefiles/taz_new_Jan14_1.shp"
url_blocks  = r"./shapefiles/blocks20a.shp"

gdf_old_taz  = gpd.read_file(url_old_taz)
gdf_new_taz  = gpd.read_file(url_new_taz)
gdf_blocks   = gpd.read_file(url_blocks)


def remove_zero_geoms(gdf):
    """
    Drop rows where geometry is None/empty OR bounding box == (0,0,0,0).
    Avoids bogus shapes that might distort the map.
    """
    def is_zero_bbox(geom):
        if geom is None or geom.is_empty:
            return True
        minx, miny, maxx, maxy = geom.bounds
        return (minx == 0 and miny == 0 and maxx == 0 and maxy == 0)
    mask = ~gdf.geometry.apply(is_zero_bbox)
    return gdf[mask].copy()

# Clean out 0,0 shapes
gdf_old_taz  = remove_zero_geoms(gdf_old_taz)
gdf_new_taz  = remove_zero_geoms(gdf_new_taz)
gdf_blocks   = remove_zero_geoms(gdf_blocks)

# -------------------------------------------------------------------------
# 2. Rename columns so each dataset is consistent
# -------------------------------------------------------------------------
# Old TAZ => must have 'taz_id'
if 'taz_id' not in gdf_old_taz.columns:
    if 'TAZ_ID' in gdf_old_taz.columns:
        gdf_old_taz = gdf_old_taz.rename(columns={'TAZ_ID': 'taz_id'})

# New TAZ => rename 'taz_new1' -> 'taz_id', 'hh19'->'HH19', etc.
rename_new = {}
if 'taz_new1' in gdf_new_taz.columns:
    rename_new['taz_new1'] = 'taz_id'
if 'hh19' in gdf_new_taz.columns:
    rename_new['hh19']      = 'HH19'
if 'persns19' in gdf_new_taz.columns:
    rename_new['persns19']  = 'PERSNS19'
if 'workrs19' in gdf_new_taz.columns:
    rename_new['workrs19']  = 'WORKRS19'
if 'emp19' in gdf_new_taz.columns:
    rename_new['emp19']     = 'EMP19'
if rename_new:
    gdf_new_taz = gdf_new_taz.rename(columns=rename_new)

# Blocks => rename 'GEOID20' -> 'BLOCK_ID' if needed
if 'GEOID20' in gdf_blocks.columns:
    gdf_blocks = gdf_blocks.rename(columns={'GEOID20': 'BLOCK_ID'})


# -------------------------------------------------------------------------
# 3. Helper Functions
# -------------------------------------------------------------------------
def latlon_to_web_mercator(gdf_in):
    """Convert a GeoDataFrame to EPSG:3857 (Web Mercator)."""
    return gdf_in.to_crs(epsg=3857)

def gdf_to_cds_polygons(gdf, id_field, ensure_cols=None):
    """
    Convert polygons to a ColumnDataSource for Bokeh .patches().
    - 'id_field' => the column used for 'id' in CDS.
    - 'ensure_cols' => list of columns to include (fill None if missing).
    """
    from bokeh.models import ColumnDataSource
    if ensure_cols is None:
        ensure_cols = []

    gdf = gdf.copy()
    for col in ensure_cols:
        if col not in gdf.columns:
            gdf[col] = None

    x_list = []
    y_list = []
    for geom in gdf.geometry:
        if geom is None or geom.is_empty:
            x_list.append([])
            y_list.append([])
            continue

        if geom.geom_type == "Polygon":
            xs, ys = geom.exterior.coords.xy
            x_list.append(xs.tolist())
            y_list.append(ys.tolist())

        elif geom.geom_type == "MultiPolygon":
            # handle shapely 2.x
            all_x, all_y = [], []
            for subpoly in geom.geoms:
                xs, ys = subpoly.exterior.coords.xy
                all_x.extend(xs.tolist() + [None])
                all_y.extend(ys.tolist() + [None])
            x_list.append(all_x)
            y_list.append(all_y)
        else:
            x_list.append([])
            y_list.append([])

    data = {
        'xs': x_list,
        'ys': y_list,
        'id': gdf[id_field].astype(str)
    }
    for col in ensure_cols:
        data[col] = gdf[col]

    return ColumnDataSource(data=data)

def sum_columns(cds, columns):
    """
    Return {col: sum_of_col} for the specified columns in a ColumnDataSource,
    ignoring non-numeric values.
    """
    data = cds.data
    out = {}
    if not data or len(data['id']) == 0:
        for c in columns:
            out[c] = 0
        return out

    for c in columns:
        s = 0
        for v in data.get(c, []):
            if isinstance(v, (int,float)):
                s += v
        out[c] = s
    return out


def filter_intersecting_data(old_taz_id):
    """
    Given an old_taz_id, find that TAZ in gdf_old_taz, then
    filter new TAZ and blocks to only the features that intersect it
    (NO buffer).
    Returns: (old_taz_web, new_taz_web, blocks_web) or (None,None,None) if not found.
    """
    if not isinstance(old_taz_id, (list, tuple)):
        old_taz_id = [old_taz_id]

    subset_old = gdf_old_taz[gdf_old_taz['taz_id'].isin(old_taz_id)]
    if subset_old.empty:
        return (None,None,None)

    # region => geometry of the old TAZ subset (no buffer)
    region = subset_old.unary_union

    subset_new    = gdf_new_taz[gdf_new_taz.intersects(region)]
    subset_blocks = gdf_blocks[gdf_blocks.intersects(region)]

    old_web    = latlon_to_web_mercator(subset_old)
    new_web    = latlon_to_web_mercator(subset_new)
    blocks_web = latlon_to_web_mercator(subset_blocks)

    return (old_web, new_web, blocks_web)


# -------------------------------------------------------------------------
# 4. Bokeh DataSources for the 4 Panels
# -------------------------------------------------------------------------
from bokeh.models import ColumnDataSource

# Top-left: Old TAZ (not selectable) + faint blocks
old_taz_source        = ColumnDataSource(dict(xs=[], ys=[], id=[]))
old_taz_blocks_source = ColumnDataSource(dict(xs=[], ys=[], id=[]))

# Top-right: New TAZ (selectable => top table) + faint blocks
new_taz_source        = ColumnDataSource(dict(xs=[], ys=[], id=[], HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[]))
new_taz_blocks_source = ColumnDataSource(dict(xs=[], ys=[], id=[]))

# Bottom-left: Combined (not selectable)
combined_old_source    = ColumnDataSource(dict(xs=[], ys=[], id=[]))
combined_new_source    = ColumnDataSource(dict(xs=[], ys=[], id=[], HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[]))
combined_blocks_source = ColumnDataSource(dict(xs=[], ys=[], id=[]))

# Bottom-right: Blocks (selectable => bottom table)
blocks_source = ColumnDataSource(dict(xs=[], ys=[], id=[], HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[]))


# -------------------------------------------------------------------------
# 5. Figures (with scroll zoom default)
# -------------------------------------------------------------------------
TOOLS_MAP = "pan,wheel_zoom,box_zoom,reset"  # we'll add tap if needed

p_old = figure(
    title="Old TAZ (top-left)", width=400, height=400,
    match_aspect=True,
    x_axis_type="mercator", y_axis_type="mercator",
    tools=TOOLS_MAP,
    active_scroll='wheel_zoom'
)

p_new = figure(
    title="New TAZ (top-right)", width=400, height=400,
    match_aspect=True,
    x_axis_type="mercator", y_axis_type="mercator",
    tools=TOOLS_MAP + ",tap",
    active_scroll='wheel_zoom'
)

p_combined = figure(
    title="Consolidated (bottom-left)", width=400, height=400,
    match_aspect=True,
    x_axis_type="mercator", y_axis_type="mercator",
    tools=TOOLS_MAP,
    active_scroll='wheel_zoom'
)

p_blocks = figure(
    title="Blocks (bottom-right)", width=400, height=400,
    match_aspect=True,
    x_axis_type="mercator", y_axis_type="mercator",
    tools=TOOLS_MAP + ",tap",
    active_scroll='wheel_zoom'
)

# Add default tile (CartoDB) to each
tile_refs = {}
def add_default_tiles(fig_list):
    from bokeh.tile_providers import CARTODBPOSITRON
    for f in fig_list:
        tile_layer = f.add_tile(CARTODBPOSITRON)
        tile_refs[f] = tile_layer

figs = [p_old, p_new, p_combined, p_blocks]
add_default_tiles(figs)


# -------------------------------------------------------------------------
# 6. Patches (Polygons) in each panel
# -------------------------------------------------------------------------
# Old TAZ + faint blocks
p_old.patches(
    xs="xs", ys="ys",
    source=old_taz_source,
    fill_color=None, line_color="green", line_width=2
)
p_old.patches(
    xs="xs", ys="ys",
    source=old_taz_blocks_source,
    fill_color=None, line_color="black", line_width=1, line_alpha=0.2
)

# New TAZ + faint blocks
p_new.patches(
    xs="xs", ys="ys",
    source=new_taz_source,
    fill_color=None, line_color="red", line_width=2,
    selection_fill_color="yellow", selection_line_color="black",
    nonselection_fill_alpha=0.1, nonselection_fill_color="red"
)
p_new.patches(
    xs="xs", ys="ys",
    source=new_taz_blocks_source,
    fill_color=None, line_color="black", line_width=1, line_alpha=0.2
)
p_new.add_tools(HoverTool(tooltips=[("New TAZ ID", "@id"), ("EMP19", "@EMP19")]))

# Combined
p_combined.patches(
    xs="xs", ys="ys",
    source=combined_blocks_source,
    fill_color="#DFBC1E", fill_alpha=0.3, line_color="black", line_dash='dotted'
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

# Blocks
p_blocks.patches(
    xs="xs", ys="ys",
    source=blocks_source,
    fill_color="#F9E79F", fill_alpha=0.5, line_color="black",
    selection_fill_color="yellow", selection_line_color="red",
    nonselection_fill_alpha=0.3
)
p_blocks.add_tools(HoverTool(tooltips=[("Block ID", "@id"), ("EMP19", "@EMP19")]))


# -------------------------------------------------------------------------
# 7. Data Tables for New TAZ (top) and Blocks (bottom)
# -------------------------------------------------------------------------
new_taz_table_source = ColumnDataSource(dict(id=[], HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[]))
blocks_table_source  = ColumnDataSource(dict(id=[], HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[]))

common_cols = [
    TableColumn(field="id",       title="ID"),
    TableColumn(field="HH19",     title="HH19"),
    TableColumn(field="PERSNS19", title="PERSNS19"),
    TableColumn(field="WORKRS19", title="WORKRS19"),
    TableColumn(field="EMP19",    title="EMP19")
]
new_taz_data_table = DataTable(source=new_taz_table_source, columns=common_cols, width=400, height=200)
blocks_data_table  = DataTable(source=blocks_table_source,  columns=common_cols, width=400, height=200)

new_taz_sum_div  = Div(text="Sum: HH19=0, PERSNS19=0, WORKRS19=0, EMP19=0")
blocks_sum_div   = Div(text="Sum: HH19=0, PERSNS19=0, WORKRS19=0, EMP19=0")


def new_taz_selection_change(attr, old, new):
    inds = new_taz_source.selected.indices
    if not inds:
        new_taz_table_source.data = dict(id=[], HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[])
        new_taz_sum_div.text = "Sum: HH19=0, PERSNS19=0, WORKRS19=0, EMP19=0"
        return
    d = {}
    for c in ["id","HH19","PERSNS19","WORKRS19","EMP19"]:
        d[c] = [new_taz_source.data[c][i] for i in inds]
    new_taz_table_source.data = d

    sums = sum_columns(new_taz_table_source, ["HH19","PERSNS19","WORKRS19","EMP19"])
    new_taz_sum_div.text = (
        f"Sum: HH19={sums['HH19']}, "
        f"PERSNS19={sums['PERSNS19']}, "
        f"WORKRS19={sums['WORKRS19']}, "
        f"EMP19={sums['EMP19']}"
    )

new_taz_source.selected.on_change("indices", new_taz_selection_change)

def blocks_selection_change(attr, old, new):
    inds = blocks_source.selected.indices
    if not inds:
        blocks_table_source.data = dict(id=[], HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[])
        blocks_sum_div.text = "Sum: HH19=0, PERSNS19=0, WORKRS19=0, EMP19=0"
        return
    d = {}
    for c in ["id","HH19","PERSNS19","WORKRS19","EMP19"]:
        d[c] = [blocks_source.data[c][i] for i in inds]
    blocks_table_source.data = d

    sums = sum_columns(blocks_table_source, ["HH19","PERSNS19","WORKRS19","EMP19"])
    blocks_sum_div.text = (
        f"Sum: HH19={sums['HH19']}, "
        f"PERSNS19={sums['PERSNS19']}, "
        f"WORKRS19={sums['WORKRS19']}, "
        f"EMP19={sums['EMP19']}"
    )

blocks_source.selected.on_change("indices", blocks_selection_change)


# -------------------------------------------------------------------------
# 8. Search TAZ + "Match Old TAZ Zoom" Toggle + Map Type Select
# -------------------------------------------------------------------------
text_input     = TextInput(value="", title="Enter Old TAZ ID:")
search_button  = Button(label="Search TAZ", button_type="success")
match_zoom_tgl = Toggle(label="Match Old TAZ Zoom", active=True)
tile_select    = Select(
    title="Map Type",
    value="CartoDB Positron",
    options=["CartoDB Positron","ESRI Satellite","Stamen Toner","Stamen Terrain"]
)
search_status_div = Div(text="<b>Currently searching TAZ:</b> (none)")


def clear_all_sources():
    """Clears all map data so panels go blank."""
    empty_ = dict(xs=[], ys=[], id=[])
    old_taz_source.data         = empty_
    old_taz_blocks_source.data  = empty_
    new_taz_source.data         = dict(xs=[], ys=[], id=[], HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[])
    new_taz_blocks_source.data  = empty_
    combined_old_source.data    = empty_
    combined_new_source.data    = dict(xs=[], ys=[], id=[], HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[])
    combined_blocks_source.data = empty_
    blocks_source.data          = dict(xs=[], ys=[], id=[], HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[])


def link_views_to_old():
    """Make all other figures match x_range/y_range objects of p_old."""
    p_new.x_range = p_old.x_range
    p_new.y_range = p_old.y_range
    p_combined.x_range = p_old.x_range
    p_combined.y_range = p_old.y_range
    p_blocks.x_range = p_old.x_range
    p_blocks.y_range = p_old.y_range


def unlink_views():
    """
    Give each figure a separate Range1d but keep the current numeric
    boundaries so they don't jump.
    """
    xstart = p_old.x_range.start
    xend   = p_old.x_range.end
    ystart = p_old.y_range.start
    yend   = p_old.y_range.end

    p_new.x_range      = Range1d(xstart, xend)
    p_new.y_range      = Range1d(ystart, yend)
    p_combined.x_range = Range1d(xstart, xend)
    p_combined.y_range = Range1d(ystart, yend)
    p_blocks.x_range   = Range1d(xstart, xend)
    p_blocks.y_range   = Range1d(ystart, yend)


def on_match_zoom_change(attr, old, new):
    """When toggling 'Match Old TAZ Zoom' on/off."""
    if new:  # turned ON => link to old TAZ
        link_views_to_old()
    else:    # turned OFF => unlink
        unlink_views()
match_zoom_tgl.on_change("active", on_match_zoom_change)


def set_tile_provider(fig, provider):
    """Remove old tile from 'tile_refs', add new provider tile."""
    old_tile = tile_refs.get(fig)
    if old_tile and old_tile in fig.renderers:
        fig.renderers.remove(old_tile)
    new_tile = fig.add_tile(provider)
    tile_refs[fig] = new_tile


def on_tile_select_change(attr, old, new):
    """Switch tile providers in all four figures."""
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


def do_search_taz():
    """Core logic for searching an Old TAZ ID and updating the panels."""
    # Show loading
    search_status_div.text = "<b>Currently searching TAZ:</b> Loading..."

    # Clear table selections
    new_taz_source.selected.update(indices=[])
    blocks_source.selected.update(indices=[])

    user_val = text_input.value.strip()
    if not user_val:
        search_status_div.text = "<b>Currently searching TAZ:</b> (No input)"
        clear_all_sources()
        return

    # Convert user_val to int
    try:
        taz_id_int = int(user_val)
    except ValueError:
        search_status_div.text = "<b>Currently searching TAZ:</b> (Invalid - not an integer)"
        clear_all_sources()
        return

    # Filter
    old_web, new_web, blocks_web = filter_intersecting_data(taz_id_int)
    if old_web is None or old_web.empty:
        search_status_div.text = f"<b>Currently searching TAZ:</b> {taz_id_int} (not found)"
        clear_all_sources()
        return

    # Build ColumnDataSources
    old_temp = gdf_to_cds_polygons(old_web, id_field="taz_id")
    blocks_for_old = gdf_to_cds_polygons(blocks_web, id_field="BLOCK_ID")

    new_temp = gdf_to_cds_polygons(new_web, id_field="taz_id",
                                   ensure_cols=["HH19","PERSNS19","WORKRS19","EMP19"])
    blocks_for_new = gdf_to_cds_polygons(blocks_web, id_field="BLOCK_ID")

    combined_old_temp    = old_temp
    combined_new_temp    = new_temp
    combined_blocks_temp = gdf_to_cds_polygons(blocks_web, id_field="BLOCK_ID")

    blocks_temp = gdf_to_cds_polygons(blocks_web, id_field="BLOCK_ID",
                                      ensure_cols=["HH19","PERSNS19","WORKRS19","EMP19"])

    # Update main sources
    old_taz_source.data         = dict(old_temp.data)
    old_taz_blocks_source.data  = dict(blocks_for_old.data)
    new_taz_source.data         = dict(new_temp.data)
    new_taz_blocks_source.data  = dict(blocks_for_new.data)
    combined_old_source.data    = dict(combined_old_temp.data)
    combined_new_source.data    = dict(combined_new_temp.data)
    combined_blocks_source.data = dict(combined_blocks_temp.data)
    blocks_source.data          = dict(blocks_temp.data)

    # Update search status
    search_status_div.text = f"<b>Currently searching TAZ:</b> {taz_id_int}"

    # Zoom to bounding box of the old_taz
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

    if match_zoom_tgl.active:
        # If "Match Old TAZ Zoom" is on => link the others
        link_views_to_old()
    else:
        # If off => give each distinct range but same numeric boundaries
        p_new.x_range      = Range1d(minx, maxx)
        p_new.y_range      = Range1d(miny, maxy)
        p_combined.x_range = Range1d(minx, maxx)
        p_combined.y_range = Range1d(miny, maxy)
        p_blocks.x_range   = Range1d(minx, maxx)
        p_blocks.y_range   = Range1d(miny, maxy)


def on_search_click():
    do_search_taz()

search_button.on_click(on_search_click)


# -------------------------------------------------------------------------
# 9. Final Layout
# -------------------------------------------------------------------------
# Two separate columns for the tables
new_taz_table_layout = column(
    Div(text="<b>New TAZ Table (top-right selection)</b>"),
    new_taz_data_table,
    new_taz_sum_div
)
blocks_table_layout = column(
    Div(text="<b>Blocks Table (bottom-right selection)</b>"),
    blocks_data_table,
    blocks_sum_div
)

# Put them in one column for the right side
tables_right = column(
    new_taz_table_layout,
    blocks_table_layout,
    width=400  # approximate ~1/4 of the total screen
)

maps_col = column(
    row(p_old, p_new),
    row(p_combined, p_blocks),
    sizing_mode="scale_width"  # let it stretch horizontally
)

top_controls = row(text_input, search_button, match_zoom_tgl, tile_select)
layout_final = column(
    top_controls,
    search_status_div,
    row(maps_col, tables_right, sizing_mode="stretch_both"),
    sizing_mode="stretch_both"
)

curdoc().add_root(layout_final)
curdoc().title = "4-Panel TAZ, No Buffer, Loading Indicator, ~3/4 vs 1/4 Layout"
