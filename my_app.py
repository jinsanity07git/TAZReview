"""
my_app.py

Requirements Addressed:
1. Bottom-right "Blocks" are NOT re-filtered when selecting new TAZ polygons.
2. Approx. 3/4 (maps) and 1/4 (tables).
3. Top row: [Enter Old TAZ ID + text] (left), "Currently Searching TAZ" (middle),
   "Selected Map Background:" + tile dropdown (right).
4. Second row: Search TAZ (left), Match 1st Panel Zoom (right).
5. If invalid TAZ, TAZ label => bold, italic, red "[TAZ Not Found]"; else black bold/italic TAZ ID.
6. Bottom-left "Combined" => blocks with translucent yellow fill.
7. All 4 panels sync to the same bounding box when searching TAZ.
8. Pressing Enter triggers search.
9. Summation row appended to each table at the bottom.

"""

import geopandas as gpd
import shapely
from shapely.geometry import Polygon, MultiPolygon
import numpy as np

from bokeh.io import curdoc
from bokeh.layouts import column, row, Spacer
from bokeh.models import (
    ColumnDataSource, DataTable, TableColumn,
    Div, TextInput, Button, Select, HoverTool, Range1d
)
from bokeh.plotting import figure
from bokeh.tile_providers import CARTODBPOSITRON, ESRI_IMAGERY

# -----------------------------------------------------------------------------
# 1. Load & Clean Shapefiles
# -----------------------------------------------------------------------------
url_old_taz = r"./shapefiles/CTPS_TDM23_TAZ_2017g_v202303.shp"
url_new_taz = r"./shapefiles/taz_new_Jan14_1.shp"
url_blocks  = r"./shapefiles/blocks20a.shp"

gdf_old_taz  = gpd.read_file(url_old_taz)
gdf_new_taz  = gpd.read_file(url_new_taz)
gdf_blocks   = gpd.read_file(url_blocks)

def remove_zero_geoms(gdf):
    """Remove geometry if empty or bounding box is (0,0,0,0)."""
    def is_zero_bbox(geom):
        if geom is None or geom.is_empty:
            return True
        minx, miny, maxx, maxy = geom.bounds
        return (minx==0 and miny==0 and maxx==0 and maxy==0)
    return gdf[~gdf.geometry.apply(is_zero_bbox)].copy()

gdf_old_taz  = remove_zero_geoms(gdf_old_taz)
gdf_new_taz  = remove_zero_geoms(gdf_new_taz)
gdf_blocks   = remove_zero_geoms(gdf_blocks)

# Convert all to EPSG:3857 to match tile providers
if gdf_old_taz.crs is None or gdf_old_taz.crs.to_string() != "EPSG:3857":
    gdf_old_taz = gdf_old_taz.to_crs(epsg=3857)
if gdf_new_taz.crs is None or gdf_new_taz.crs.to_string() != "EPSG:3857":
    gdf_new_taz = gdf_new_taz.to_crs(epsg=3857)
if gdf_blocks.crs is None or gdf_blocks.crs.to_string() != "EPSG:3857":
    gdf_blocks = gdf_blocks.to_crs(epsg=3857)

# -----------------------------------------------------------------------------
# 2. Rename columns
# -----------------------------------------------------------------------------
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
    rename_map_new['emp19']  = 'EMP19'
if rename_map_new:
    gdf_new_taz = gdf_new_taz.rename(columns=rename_map_new)

if 'GEOID20' in gdf_blocks.columns:
    gdf_blocks = gdf_blocks.rename(columns={'GEOID20':'BLOCK_ID'})

# -----------------------------------------------------------------------------
# 3. Helper Functions
# -----------------------------------------------------------------------------
from bokeh.models import ColumnDataSource

def split_multipolygons_to_cds(gdf, id_field, ensure_cols=None):
    """
    Each sub-polygon => separate row => no KeyError in selection.
    """
    if ensure_cols is None:
        ensure_cols = []
    for c in ensure_cols:
        if c not in gdf.columns:
            gdf[c] = None

    all_xs, all_ys, all_ids = [], [], []
    attr_data = {c: [] for c in ensure_cols}

    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        row_id = str(row[id_field])
        row_attrs = {c: row[c] for c in ensure_cols}

        if geom.geom_type=="MultiPolygon":
            for subpoly in geom.geoms:
                xs, ys = subpoly.exterior.coords.xy
                all_xs.append(xs.tolist())
                all_ys.append(ys.tolist())
                all_ids.append(row_id)
                for c in ensure_cols:
                    attr_data[c].append(row_attrs[c])
        elif geom.geom_type=="Polygon":
            xs, ys = geom.exterior.coords.xy
            all_xs.append(xs.tolist())
            all_ys.append(ys.tolist())
            all_ids.append(row_id)
            for c in ensure_cols:
                attr_data[c].append(row_attrs[c])
    data = {'xs': all_xs, 'ys': all_ys, 'id': all_ids}
    for c in ensure_cols:
        data[c] = attr_data[c]
    return ColumnDataSource(data)

def filter_by_old_taz(old_id_int):
    """Return (old_subset, new_subset, blocks_subset) that intersect old TAZ geometry."""
    subset_old = gdf_old_taz[gdf_old_taz['taz_id']==old_id_int]
    if subset_old.empty:
        return (None, None, None)
    region = subset_old.unary_union
    new_sub = gdf_new_taz[gdf_new_taz.intersects(region)]
    blocks_sub = gdf_blocks[gdf_blocks.intersects(region)]
    return (subset_old, new_sub, blocks_sub)

def add_sum_row(d, colnames):
    """Append a 'Sum' row with the numeric sums at the bottom."""
    if not d or not d['id']:
        return d
    sums = {c:0 for c in colnames}
    for c in colnames:
        for val in d[c]:
            if isinstance(val, (int,float)):
                sums[c]+=val
    d['id'].append("Sum")
    for c in colnames:
        d[c].append(sums[c])
    return d

# -----------------------------------------------------------------------------
# 4. DataSources
# -----------------------------------------------------------------------------
old_taz_source        = ColumnDataSource(dict(xs=[], ys=[], id=[]))
old_taz_blocks_source = ColumnDataSource(dict(xs=[], ys=[], id=[]))

new_taz_source        = ColumnDataSource(dict(xs=[], ys=[], id=[], HH19=[],PERSNS19=[],WORKRS19=[],EMP19=[]))
new_taz_blocks_source = ColumnDataSource(dict(xs=[], ys=[], id=[]))

combined_old_source    = ColumnDataSource(dict(xs=[], ys=[], id=[]))
combined_new_source    = ColumnDataSource(dict(xs=[], ys=[], id=[], HH19=[],PERSNS19=[],WORKRS19=[],EMP19=[]))
combined_blocks_source = ColumnDataSource(dict(xs=[], ys=[], id=[]))

blocks_source = ColumnDataSource(dict(xs=[], ys=[], id=[],HH19=[],PERSNS19=[],WORKRS19=[],EMP19=[]))

global_new_gdf    = None
global_blocks_gdf = None

# -----------------------------------------------------------------------------
# 5. Figures
# -----------------------------------------------------------------------------
TOOLS = "pan,wheel_zoom,box_zoom,reset"

p_old = figure(
    title="1) Old TAZ",
    match_aspect=True,
    tools=TOOLS, active_scroll='wheel_zoom',
    x_axis_type="mercator", y_axis_type="mercator",
    sizing_mode="scale_both"
)

p_new = figure(
    title="2) New TAZ (blocks not selectable)",
    match_aspect=True,
    tools=TOOLS + ",tap", active_scroll='wheel_zoom',
    x_axis_type="mercator", y_axis_type="mercator",
    sizing_mode="scale_both"
)

p_combined = figure(
    title="3) Combined (not selectable)",
    match_aspect=True,
    tools=TOOLS, active_scroll='wheel_zoom',
    x_axis_type="mercator", y_axis_type="mercator",
    sizing_mode="scale_both"
)

p_blocks = figure(
    title="4) Blocks (selectable)",
    match_aspect=True,
    tools=TOOLS + ",tap", active_scroll='wheel_zoom',
    x_axis_type="mercator", y_axis_type="mercator",
    sizing_mode="scale_both"
)

# Add tile providers
tile_map = {}
def add_tiles():
    for fig_ in [p_old, p_new, p_combined, p_blocks]:
        tile = fig_.add_tile(CARTODBPOSITRON)
        tile_map[fig_] = tile

add_tiles()

# -----------------------------------------------------------------------------
# 6. Patch Glyphs
# -----------------------------------------------------------------------------
# Panel #1
p_old.patches(
    xs="xs", ys="ys", source=old_taz_source,
    fill_color=None, line_color="green", line_width=2
)
p_old.patches(
    xs="xs", ys="ys", source=old_taz_blocks_source,
    fill_color=None, line_color="black", line_width=2, line_dash='dotted'
)

# Panel #2 => TAZ polygons selectable
taz_glyph_new = p_new.patches(
    xs="xs", ys="ys",
    source=new_taz_source,
    fill_color=None, line_color="red", line_width=2,
    selection_fill_color=None,    
    selection_line_color="yellow", selection_line_width=2,
    nonselection_fill_color=None, 
    nonselection_line_color="red",
)
blocks_glyph_new = p_new.patches(
    xs="xs", ys="ys",
    source=new_taz_blocks_source,
    fill_color=None, line_color="black", line_width=2, line_dash='dotted'
)
p_new.add_tools(HoverTool(tooltips=[("New TAZ ID","@id"), ("EMP19","@EMP19")], renderers=[taz_glyph_new]))

# Panel #3 => combined
# Make blocks translucent yellow
p_combined.patches(
    xs="xs", ys="ys",
    source=combined_blocks_source,
    fill_color="yellow", fill_alpha=0.3,
    line_color="black", line_width=2, line_dash='dotted'
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

# Panel #4 => blocks (selectable)
p_blocks.patches(
    xs="xs", ys="ys",
    source=blocks_source,
    fill_color="#F9E79F", fill_alpha=0.5,
    line_color="black", line_width=2, line_dash='dotted',
    selection_fill_color="yellow", selection_line_color="red",
    nonselection_fill_alpha=0.3
)

# -----------------------------------------------------------------------------
# 7. Tables + Summation
# -----------------------------------------------------------------------------
new_taz_table_source = ColumnDataSource(dict(id=[],HH19=[],PERSNS19=[],WORKRS19=[],EMP19=[]))
blocks_table_source  = ColumnDataSource(dict(id=[],HH19=[],PERSNS19=[],WORKRS19=[],EMP19=[]))

table_cols = [
    TableColumn(field="id",       title="ID"),
    TableColumn(field="HH19",     title="HH19"),
    TableColumn(field="PERSNS19", title="PERSNS19"),
    TableColumn(field="WORKRS19", title="WORKRS19"),
    TableColumn(field="EMP19",    title="EMP19"),
]
new_taz_data_table = DataTable(source=new_taz_table_source, columns=table_cols, width=350, height=200)
blocks_data_table  = DataTable(source=blocks_table_source,  columns=table_cols, width=350, height=200)

def update_new_taz_table():
    inds = new_taz_source.selected.indices
    if not inds:
        new_taz_table_source.data = dict(id=[],HH19=[],PERSNS19=[],WORKRS19=[],EMP19=[])
        return
    d={}
    for c in ["id","HH19","PERSNS19","WORKRS19","EMP19"]:
        d[c] = [new_taz_source.data[c][i] for i in inds]
    d = add_sum_row(d, ["HH19","PERSNS19","WORKRS19","EMP19"])
    new_taz_table_source.data = d

def update_blocks_table():
    inds = blocks_source.selected.indices
    if not inds:
        blocks_table_source.data = dict(id=[],HH19=[],PERSNS19=[],WORKRS19=[],EMP19=[])
        return
    d={}
    for c in ["id","HH19","PERSNS19","WORKRS19","EMP19"]:
        d[c] = [blocks_source.data[c][i] for i in inds]
    d = add_sum_row(d, ["HH19","PERSNS19","WORKRS19","EMP19"])
    blocks_table_source.data = d

new_taz_source.selected.on_change("indices", lambda attr, old, new: update_new_taz_table())
blocks_source.selected.on_change("indices",  lambda attr, old, new: update_blocks_table())

# -----------------------------------------------------------------------------
# 8. Searching TAZ
# -----------------------------------------------------------------------------
search_label = Div(text="<b>Currently Searching TAZ: </b><b><i>(none)</i></b>", width=300)
text_label   = Div(text="<b>Enter Old TAZ ID:</b>", width=120)
text_input   = TextInput(value="", title="", placeholder="TAZ ID...", width=100)
search_button= Button(label="Search TAZ", button_type="success", width=80)
match_zoom_btn = Button(label="Match 1st Panel Zoom", width=130)

tile_label   = Div(text="<b>Selected Map Background:</b>", width=150)
tile_select  = Select(
    title="",  # we'll use tile_label instead
    value="CartoDB Positron",
    options=["CartoDB Positron","ESRI Satellite"],
    width=140
)

def do_search():
    val = text_input.value.strip()
    if not val:
        # no input
        search_label.text = "<b>Currently Searching TAZ: </b><b><i>(no input)</i></b>"
        return
    try:
        old_id_int = int(val)
    except ValueError:
        # invalid
        search_label.text = "<b>Currently Searching TAZ: </b><b><i style='color:red'>[TAZ Not Found]</i></b>"
        return
    # filter
    o, n, b = filter_by_old_taz(old_id_int)
    if o is None or o.empty:
        search_label.text = "<b>Currently Searching TAZ: </b><b><i style='color:red'>[TAZ Not Found]</i></b>"
        return
    # Valid TAZ => display ID in bold+italic black
    search_label.text = f"<b>Currently Searching TAZ: </b><b><i>{old_id_int}</i></b>"

    # store references
    global global_new_gdf, global_blocks_gdf
    global_new_gdf    = n
    global_blocks_gdf = b

    # Convert to CDS
    old_temp = split_multipolygons_to_cds(o, "taz_id")
    new_temp = split_multipolygons_to_cds(n, "taz_id", ["HH19","PERSNS19","WORKRS19","EMP19"])
    blocks_temp = split_multipolygons_to_cds(b, "BLOCK_ID", ["HH19","PERSNS19","WORKRS19","EMP19"])
    old_blocks_temp = split_multipolygons_to_cds(b, "BLOCK_ID")
    new_blocks_temp = split_multipolygons_to_cds(b, "BLOCK_ID")
    comb_old_temp   = old_temp
    comb_new_temp   = new_temp
    comb_blocks_temp= split_multipolygons_to_cds(b, "BLOCK_ID")

    old_taz_source.data         = dict(old_temp.data)
    new_taz_source.data         = dict(new_temp.data)
    blocks_source.data          = dict(blocks_temp.data)
    old_taz_blocks_source.data  = dict(old_blocks_temp.data)
    new_taz_blocks_source.data  = dict(new_blocks_temp.data)
    combined_old_source.data    = dict(comb_old_temp.data)
    combined_new_source.data    = dict(comb_new_temp.data)
    combined_blocks_source.data = dict(comb_blocks_temp.data)

    # Clear table & selection
    new_taz_source.selected.indices = []
    blocks_source.selected.indices  = []
    new_taz_table_source.data = dict(id=[],HH19=[],PERSNS19=[],WORKRS19=[],EMP19=[])
    blocks_table_source.data  = dict(id=[],HH19=[],PERSNS19=[],WORKRS19=[],EMP19=[])

    # Zoom p_old
    minx, miny, maxx, maxy = o.total_bounds
    if minx==maxx or miny==maxy:
        minx-=1000; maxx+=1000
        miny-=1000; maxy+=1000
    else:
        dx = maxx-minx
        dy = maxy-miny
        minx-=0.05*dx
        maxx+=0.05*dx
        miny-=0.05*dy
        maxy+=0.05*dy

    p_old.x_range.start = minx
    p_old.x_range.end   = maxx
    p_old.y_range.start = miny
    p_old.y_range.end   = maxy

    # Match p_old range => p_new, p_combined, p_blocks
    p_new.x_range.start      = minx
    p_new.x_range.end        = maxx
    p_new.y_range.start      = miny
    p_new.y_range.end        = maxy

    p_combined.x_range.start = minx
    p_combined.x_range.end   = maxx
    p_combined.y_range.start = miny
    p_combined.y_range.end   = maxy

    p_blocks.x_range.start   = minx
    p_blocks.x_range.end     = maxx
    p_blocks.y_range.start   = miny
    p_blocks.y_range.end     = maxy

def on_search_click():
    do_search()

search_button.on_click(on_search_click)

def on_text_input_change(attr, old, new):
    """Pressing Enter or losing focus calls do_search()."""
    do_search()

text_input.on_change("value", on_text_input_change)

def on_tile_change(attr, old, new):
    provider = CARTODBPOSITRON if new=="CartoDB Positron" else ESRI_IMAGERY
    for fig_ in [p_old, p_new, p_combined, p_blocks]:
        old_tile = tile_map.get(fig_)
        if old_tile and old_tile in fig_.renderers:
            fig_.renderers.remove(old_tile)
        new_t = fig_.add_tile(provider)
        tile_map[fig_] = new_t

tile_select.on_change("value", on_tile_change)

def on_match_zoom_click():
    # copy p_old ranges => p_new, p_combined, p_blocks
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

match_zoom_btn.on_click(on_match_zoom_click)

# -----------------------------------------------------------------------------
# 9. Layout
# -----------------------------------------------------------------------------
# Row 1:
row1_left = row(text_label, text_input, Spacer(width=40))
row1_center = row(search_label, sizing_mode="fixed")
row1_right_label = Div(text="<b>Selected Map Background:</b>", width=150)
row1_right = row(row1_right_label, tile_select)

row1 = row(
    row1_left,
    row1_center,
    row1_right,
    sizing_mode="stretch_width"
)

# Row 2: search TAZ (left) + match zoom (right)
# The "Currently Searching TAZ" is already in row1 now
row2_left  = row(search_button, Spacer(width=30))
row2_right = row(match_zoom_btn)
row2 = row(row2_left, Spacer(width=300), row2_right, sizing_mode="stretch_width")

# 2×2 panels => left side
top_maps = row(p_old, p_new, sizing_mode="scale_both")
bottom_maps = row(p_combined, p_blocks, sizing_mode="scale_both")
maps_col = column(top_maps, bottom_maps, sizing_mode="scale_both")

# Right side => two tables ~ 1/4 width
top_table = column(Div(text="<b>New TAZ Table</b>"), new_taz_data_table)
bottom_table = column(Div(text="<b>Blocks Table</b>"), blocks_data_table)
tables_col = column(top_table, bottom_table, width=350, sizing_mode="scale_both")

# main row => ~3/4 + 1/4
main_row = row(maps_col, tables_col, sizing_mode="stretch_both")

layout_final = column(
    row1,
    row2,
    main_row,
    sizing_mode="stretch_both"
)

curdoc().add_root(layout_final)
curdoc().title = "4-Panel TAZ (3/4 maps, 1/4 tables) with top UI and no block re-filter"
