"""
my_app.py

Run with:
    bokeh serve --show my_app.py

Then visit:
    http://localhost:5006/my_app

Columns for shapefiles/blocks20a.shp: ['STATEFP20', 'COUNTYFP20', 'TRACTCE20', 'BLOCKCE20', 'GEOID20', 'ALAND20', 'AWATER20', 'COUSUBFP', 'NAME', 'Shape_Leng', 'Shape_Area', 'town_id', 'MPO', 'taz_id0', 'taz_new1', 'HH19', 'PERSNS19', 'WORKRS19', 'EMP19', 'HH49', 'PERSNS49', 'WORKRS49', 'EMP49', 'geometry']

Columns for shapefiles/CTPS_TDM23_TAZ_2017g_v202303.shp: ['OBJECTID', 'taz_id', 'Shape_Leng', 'Shape_Area', 'type', 'town', 'state', 'town_state', 'mpo', 'in_brmpo', 'subregion', 'ring', 'corridor', 'district', 'total_area', 'land_area', 'urban', 'geometry']

Columns for shapefiles/taz_new_Jan14_1.shp: ['NAME', 'town_id', 'MPO', 'taz_new1', 'hh19', 'persns19', 'workrs19', 'emp19', 'hh49', 'persns49', 'workrs49', 'emp49', 'Shape_Leng', 'Shape_Area', 'geometry']
"""

import geopandas as gpd
import shapely
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import transform  # if you need to drop Z dimension
import numpy as np

from bokeh.io import curdoc
from bokeh.layouts import column, row
from bokeh.models import (
    ColumnDataSource, DataTable, TableColumn,
    TextInput, TapTool, HoverTool, Div
)
from bokeh.plotting import figure
from bokeh.tile_providers import CARTODBPOSITRON

# -----------------------------------------------------------------------------
# 1. Load your Shapefiles
# -----------------------------------------------------------------------------
url_old_taz  = r"./shapefiles/CTPS_TDM23_TAZ_2017g_v202303.shp"
url_new_taz  = r"./shapefiles/taz_new_Jan14_1.shp"
url_blocks   = r"./shapefiles/blocks20a.shp"

gdf_old_taz  = gpd.read_file(url_old_taz)
gdf_new_taz  = gpd.read_file(url_new_taz)
gdf_blocks   = gpd.read_file(url_blocks)

# -----------------------------------------------------------------------------
# 2. Rename columns so each dataset is consistent
#    - Old TAZ -> must have 'taz_id'
#    - New TAZ -> rename 'taz_new1' to 'taz_id', 'hh19'->'HH19', etc.
#    - Blocks  -> rename 'GEOID20' to 'BLOCK_ID'
# -----------------------------------------------------------------------------

# Old TAZ: if it already has 'taz_id', we do nothing.
if 'taz_id' not in gdf_old_taz.columns:
    # For example, if it uses 'TAZ_ID'
    if 'TAZ_ID' in gdf_old_taz.columns:
        gdf_old_taz = gdf_old_taz.rename(columns={'TAZ_ID': 'taz_id'})

# New TAZ: rename 'taz_new1' -> 'taz_id' and lowercase columns to uppercase
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

# Blocks: rename 'GEOID20' -> 'BLOCK_ID' if needed
if 'GEOID20' in gdf_blocks.columns:
    gdf_blocks = gdf_blocks.rename(columns={'GEOID20': 'BLOCK_ID'})

# Now:
# - Old TAZ should have 'taz_id'
# - New TAZ should have 'taz_id'
# - Blocks should have 'BLOCK_ID'
# - All with 'HH19', 'PERSNS19', 'WORKRS19', 'EMP19' if relevant

# -----------------------------------------------------------------------------
# 3. Helper Functions
# -----------------------------------------------------------------------------

def latlon_to_web_mercator(gdf_in):
    """
    Convert a GeoDataFrame to EPSG:3857 for Bokeh tile-based plotting.
    If data is already in EPSG:3857, this will do nothing.
    """
    return gdf_in.to_crs(epsg=3857)

def gdf_to_bokeh_source(gdf, id_field):
    """
    Convert a *filtered* GeoDataFrame into a Bokeh ColumnDataSource for .patches().
    Handles Polygons and MultiPolygons with Shapely 2.x.

    Expects that gdf has columns: [id_field, 'HH19', 'PERSNS19', 'WORKRS19', 'EMP19'] 
    (some may be missing => fill with None).
    """
    gdf = gdf.copy()

    # Make sure columns exist
    needed_cols = ['HH19', 'PERSNS19', 'WORKRS19', 'EMP19']
    for col in needed_cols:
        if col not in gdf.columns:
            gdf[col] = None
    
    x_list = []
    y_list = []
    for geom in gdf.geometry:
        if geom is None or geom.is_empty:
            x_list.append([])
            y_list.append([])
            continue
        
        # Drop Z dimension if needed:
        # geom = transform(lambda x, y, z=None: (x, y), geom)

        if geom.geom_type == "Polygon":
            xs, ys = geom.exterior.coords.xy
            x_list.append(xs.tolist())
            y_list.append(ys.tolist())
        elif geom.geom_type == "MultiPolygon":
            # Shapely 2.x => iterate over geom.geoms
            all_x = []
            all_y = []
            for subpoly in geom.geoms:
                xs, ys = subpoly.exterior.coords.xy
                # Insert None between sub-polygons so Bokeh draws breaks
                all_x.extend(xs.tolist() + [None])
                all_y.extend(ys.tolist() + [None])
            x_list.append(all_x)
            y_list.append(all_y)
        else:
            # If other geometry types appear, skip or handle them
            x_list.append([])
            y_list.append([])

    data_dict = {
        'xs': x_list,
        'ys': y_list,
        'id': gdf[id_field].astype(str),
        'HH19':      gdf['HH19'],
        'PERSNS19':  gdf['PERSNS19'],
        'WORKRS19':  gdf['WORKRS19'],
        'EMP19':     gdf['EMP19'],
    }
    return ColumnDataSource(data=data_dict)

def filter_data(old_taz_id):
    """
    Filter the old TAZ, new TAZ, and blocks to the region around the given old_taz_id,
    using a buffer. Then convert each to EPSG:3857.
    """
    # Convert ID to list if it's a single int
    if not isinstance(old_taz_id, (list, tuple)):
        old_taz_id = [old_taz_id]
    
    old_filtered = gdf_old_taz[gdf_old_taz['taz_id'].isin(old_taz_id)]
    if old_filtered.empty:
        return old_filtered, None, None
    
    buffer_distance = 5 * 1609.34  # 5 miles in meters
    buffer_area = old_filtered.buffer(buffer_distance).unary_union

    new_filtered    = gdf_new_taz[gdf_new_taz.intersects(buffer_area)]
    blocks_filtered = gdf_blocks[gdf_blocks.intersects(buffer_area)]

    old_web    = latlon_to_web_mercator(old_filtered)
    new_web    = latlon_to_web_mercator(new_filtered)
    blocks_web = latlon_to_web_mercator(blocks_filtered)

    return old_web, new_web, blocks_web

def update_maps():
    """
    Called whenever the user changes the text input.
    - Filter data
    - Update ColumnDataSources
    - Reset map ranges
    """
    user_input_val = text_input.value.strip()
    if not user_input_val:
        return
    
    # Convert user input to integer if TAZ IDs are integers
    try:
        old_id = int(user_input_val)
    except ValueError:
        return  # or handle error
    
    old_web, new_web, blocks_web = filter_data(old_id)
    
    if old_web is None or old_web.empty:
        # Clear everything if no data
        old_source.data    = dict(xs=[], ys=[], id=[], HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[])
        new_source.data    = dict(xs=[], ys=[], id=[], HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[])
        blocks_source.data = dict(xs=[], ys=[], id=[], HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[])
        combined_old_source.data    = dict(old_source.data)
        combined_new_source.data    = dict(new_source.data)
        combined_blocks_source.data = dict(blocks_source.data)
        return

    # Build temp CDS
    old_temp    = gdf_to_bokeh_source(old_web, 'taz_id')
    new_temp    = gdf_to_bokeh_source(new_web, 'taz_id')
    blocks_temp = gdf_to_bokeh_source(blocks_web, 'BLOCK_ID')
    
    # Update main sources (copy dict to avoid Bokeh 3.x error)
    old_source.data    = dict(old_temp.data)
    new_source.data    = dict(new_temp.data)
    blocks_source.data = dict(blocks_temp.data)

    # Update combined (copy dict)
    combined_old_source.data    = dict(old_source.data)
    combined_new_source.data    = dict(new_source.data)
    combined_blocks_source.data = dict(blocks_source.data)

    # Recenter maps to the bounding box of old_web (or combined)
    bounds = old_web.total_bounds  # [minx, miny, maxx, maxy]
    # If it's empty, fallback to new_web or blocks_web
    minx, miny, maxx, maxy = bounds
    expand_factor = 0.05
    dx = maxx - minx
    dy = maxy - miny

    if dx == 0 or dy == 0:
        # Avoid zero-range error if it's a single point (unlikely, but possible)
        dx = 1000
        dy = 1000

    minx -= expand_factor * dx
    maxx += expand_factor * dx
    miny -= expand_factor * dy
    maxy += expand_factor * dy

    # Update range for all subplots
    for fig_ in [p_old, p_new, p_blocks, p_combined]:
        fig_.x_range.start = minx
        fig_.x_range.end   = maxx
        fig_.y_range.start = miny
        fig_.y_range.end   = maxy

def update_data_table(layer_source):
    """
    Called when user taps polygons in old/new/blocks figures.
    Display attributes of the selected polygons in the data table on the right.
    """
    selected_indices = layer_source.selected.indices
    if not selected_indices:
        # If nothing selected, clear the table
        table_source.data = {k: [] for k in table_source.data.keys()}
        return
    
    data = layer_source.data
    new_data = {}
    for col_name in data.keys():
        new_data[col_name] = [data[col_name][i] for i in selected_indices]
    
    table_source.data = new_data

# -----------------------------------------------------------------------------
# 4. Bokeh ColumnDataSources
# -----------------------------------------------------------------------------
old_source    = ColumnDataSource(dict(xs=[], ys=[], id=[], HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[]))
new_source    = ColumnDataSource(dict(xs=[], ys=[], id=[], HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[]))
blocks_source = ColumnDataSource(dict(xs=[], ys=[], id=[], HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[]))

combined_old_source    = ColumnDataSource(dict(xs=[], ys=[], id=[], HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[]))
combined_new_source    = ColumnDataSource(dict(xs=[], ys=[], id=[], HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[]))
combined_blocks_source = ColumnDataSource(dict(xs=[], ys=[], id=[], HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[]))

# -----------------------------------------------------------------------------
# 5. Bokeh Figures (4 panels)
# -----------------------------------------------------------------------------
common_tools = "pan,wheel_zoom,box_zoom,reset,tap"

p_old = figure(
    title="Old TAZ",
    match_aspect=True,
    x_axis_type="mercator", y_axis_type="mercator",
    tools=common_tools,
    active_scroll='wheel_zoom'
)
p_old.add_tile(CARTODBPOSITRON)

p_new = figure(
    title="New TAZ",
    match_aspect=True,
    x_axis_type="mercator", y_axis_type="mercator",
    tools=common_tools,
    active_scroll='wheel_zoom'
)
p_new.add_tile(CARTODBPOSITRON)

p_blocks = figure(
    title="Blocks",
    match_aspect=True,
    x_axis_type="mercator", y_axis_type="mercator",
    tools=common_tools,
    active_scroll='wheel_zoom'
)
p_blocks.add_tile(CARTODBPOSITRON)

p_combined = figure(
    title="Combined",
    match_aspect=True,
    x_axis_type="mercator", y_axis_type="mercator",
    tools="pan,wheel_zoom,box_zoom,reset",  # No tap tool for combined
    active_scroll='wheel_zoom'
)
p_combined.add_tile(CARTODBPOSITRON)

# -----------------------------------------------------------------------------
# 6. Add polygon (patches) glyphs
# -----------------------------------------------------------------------------
# Old TAZ
glyph_old = p_old.patches(
    xs="xs", ys="ys",
    source=old_source,
    fill_color=None, line_color="green", line_width=2,
    selection_fill_color="yellow", selection_line_color="black",
    nonselection_fill_alpha=0.1, nonselection_fill_color="green"
)
p_old.add_tools(HoverTool(tooltips=[("Old TAZ ID", "@id")]))

# New TAZ
glyph_new = p_new.patches(
    xs="xs", ys="ys",
    source=new_source,
    fill_color=None, line_color="red", line_width=2,
    selection_fill_color="yellow", selection_line_color="black",
    nonselection_fill_alpha=0.1, nonselection_fill_color="red"
)
p_new.add_tools(HoverTool(tooltips=[("New TAZ ID", "@id")]))

# Blocks
glyph_blocks = p_blocks.patches(
    xs="xs", ys="ys",
    source=blocks_source,
    fill_color="#F9E79F", line_color="black", fill_alpha=0.5,
    selection_fill_color="yellow", selection_line_color="red",
    nonselection_fill_alpha=0.3
)
p_blocks.add_tools(HoverTool(tooltips=[("Block ID", "@id")]))

# Combined: old + new + blocks
glyph_comb_blocks = p_combined.patches(
    xs="xs", ys="ys",
    source=combined_blocks_source,
    fill_color="#DFBC1E", fill_alpha=0.3, line_color="black", line_dash='dotted'
)
glyph_comb_old = p_combined.patches(
    xs="xs", ys="ys",
    source=combined_old_source,
    fill_color=None, line_color="green", line_width=2
)
glyph_comb_new = p_combined.patches(
    xs="xs", ys="ys",
    source=combined_new_source,
    fill_color=None, line_color="red", line_width=2
)

# -----------------------------------------------------------------------------
# 7. DataTable for selected features
# -----------------------------------------------------------------------------
table_source = ColumnDataSource(dict(
    id=[], HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[]
))

columns = [
    TableColumn(field="id",        title="ID"),
    TableColumn(field="HH19",      title="HH19"),
    TableColumn(field="PERSNS19",  title="PERSNS19"),
    TableColumn(field="WORKRS19",  title="WORKRS19"),
    TableColumn(field="EMP19",     title="EMP19")
]
data_table = DataTable(source=table_source, columns=columns, width=400, height=300)

# When user selects polygons, update the table
def old_selection_change(attr, old, new):
    update_data_table(old_source)
old_source.selected.on_change("indices", old_selection_change)

def new_selection_change(attr, old, new):
    update_data_table(new_source)
new_source.selected.on_change("indices", new_selection_change)

def blocks_selection_change(attr, old, new):
    update_data_table(blocks_source)
blocks_source.selected.on_change("indices", blocks_selection_change)

# -----------------------------------------------------------------------------
# 8. Text Input for Old TAZ ID
# -----------------------------------------------------------------------------
text_input = TextInput(value="", title="Enter Old TAZ ID:")

# When the text changes, re-filter & update maps
text_input.on_change("value", lambda attr, old, new: update_maps())

# -----------------------------------------------------------------------------
# 9. Final layout
# -----------------------------------------------------------------------------
maps_layout = row(
    column(p_old, p_blocks),
    column(p_new, p_combined)
)

right_side = column(
    Div(text="<b>Selected Feature Attributes</b>"),
    data_table
)

final_layout = column(text_input, row(maps_layout, right_side))

curdoc().add_root(final_layout)
curdoc().title = "TAZ vs Blocks - Bokeh App"
