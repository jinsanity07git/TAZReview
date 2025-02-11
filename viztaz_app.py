"""
viztaz_app.py

---------------------------------
bokeh serve --show viztaz_app.py
---------------------------------

Features:
 - Top row: left = Enter Old TAZ ID, center = "Currently Searching TAZ: #/Not Found", 
   right = "Selected Map Background" + dropdown
 - Second row: "Search TAZ" + "Match 1st Panel Zoom" side by side
 - Main layout: ~3/4 maps (left) + ~1/4 tables (right)
 - Automatic zoom matching on TAZ search
 - TAZ polygons (red + yellow fill on selection) and blocks (yellow + black dotted on selection)
 - Old TAZ = blue in top-left & combined, plus neighbor outlines in gray (dotted)
 - Summation row always at table bottom, bolded
 - TAZ ID in green if found, or red "[TAZ Not Found]" if invalid

Modifications in this version:
 1. Map titles are always visible (added via external Divs).
 2. New TAZ and blocks are filtered based on intersection with a 1‑km buffer (previously 2 km) 
    around the centroid of the old TAZ, but their full original shapes are displayed.
 3. A light–red filled 1‑km “buffer” is drawn on the old TAZ (1st) panel.
 4. The hover tool that displayed x and y coordinates and index:0 in the top left has been removed.
 5. The old TAZ layer remains non–clickable.
 6. Additionally, all old TAZ features that intersect the 1‑km buffer are outlined 
    (gray, dotted) so you can see all the neighboring areas.
 7. Shapefiles are read from folders (one bundle per folder).
 8. The tables now also include additional 2049 data columns.
 9. The tables are now horizontally scrollable, with columns made a bit narrower.
10. Extra text box for comma-delimited TAZ IDs displays additional old TAZ shapes in purple.
11. TAZ IDs are now drawn as text labels: on the top–left (old TAZ) in blue and on the top–right (new TAZ) in red.
12. The text labels are bolded.
13. The hover tooltip showing a TAZ ID appears only when the mouse is over the actual TAZ polygon.
14. Top right (new TAZ) hover now shows TAZ ID, HH19, EMP19, HH49, and EMP49. Their values are pre-formatted to 1 decimal.
15. Bottom right (blocks) hover now shows Block ID, HH19, EMP19, HH49, and EMP49 (formatted similarly).
16. Scientific notation is turned off and axis tick labels use a format that trims insignificant trailing zeros.
17. The extra TAZ search is triggered both by clicking its button and by pressing Enter/Tab in the extra search box.
"""

import os, glob
import geopandas as gpd
from shapely.geometry import Polygon, MultiPolygon
import numpy as np

from bokeh.io import curdoc
from bokeh.layouts import column, row, Spacer
from bokeh.models import (
    ColumnDataSource, DataTable, TableColumn,
    Div, TextInput, Button, Select, HoverTool
)
from bokeh.models.widgets.tables import HTMLTemplateFormatter
from bokeh.plotting import figure
from bokeh.tile_providers import CARTODBPOSITRON, ESRI_IMAGERY
from bokeh.models import NumeralTickFormatter

# -----------------------------------------------------------------------------
# 1. Read Shapefiles from Respective Folders
# -----------------------------------------------------------------------------
old_taz_folder = "./shapefiles/old_taz_shapefile"   # folder containing old TAZ shapefile components
new_taz_folder = "./shapefiles/new_taz_shapefile"     # folder containing new TAZ shapefile components
blocks_folder  = "./shapefiles/blocks_shapefile"      # folder containing blocks shapefile components

def find_shapefile_in_folder(folder):
    shp_files = glob.glob(os.path.join(folder, "*.shp"))
    if not shp_files:
        raise FileNotFoundError(f"No shapefile found in folder: {folder}")
    return shp_files[0]

url_old_taz = find_shapefile_in_folder(old_taz_folder)
url_new_taz = find_shapefile_in_folder(new_taz_folder)
url_blocks  = find_shapefile_in_folder(blocks_folder)

gdf_old_taz  = gpd.read_file(url_old_taz)
gdf_new_taz  = gpd.read_file(url_new_taz)
gdf_blocks   = gpd.read_file(url_blocks)

def remove_zero_geoms(gdf):
    def is_zero_bbox(geom):
        if geom is None or geom.is_empty:
            return True
        minx, miny, maxx, maxy = geom.bounds
        return (minx == 0 and miny == 0 and maxx == 0 and maxy == 0)
    return gdf[~gdf.geometry.apply(is_zero_bbox)].copy()

gdf_old_taz  = remove_zero_geoms(gdf_old_taz)
gdf_new_taz  = remove_zero_geoms(gdf_new_taz)
gdf_blocks   = remove_zero_geoms(gdf_blocks)

# Convert to EPSG:3857 for tile providers
if gdf_old_taz.crs is None or gdf_old_taz.crs.to_string() != "EPSG:3857":
    gdf_old_taz = gdf_old_taz.to_crs(epsg=3857)
if gdf_new_taz.crs is None or gdf_new_taz.crs.to_string() != "EPSG:3857":
    gdf_new_taz = gdf_new_taz.to_crs(epsg=3857)
if gdf_blocks.crs is None or gdf_blocks.crs.to_string() != "EPSG:3857":
    gdf_blocks = gdf_blocks.to_crs(epsg=3857)

# Rename columns if needed
if 'taz_id' not in gdf_old_taz.columns:
    if 'TAZ_ID' in gdf_old_taz.columns:
        gdf_old_taz = gdf_old_taz.rename(columns={'TAZ_ID': 'taz_id'})

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
if 'hh49' in gdf_new_taz.columns:
    rename_map_new['hh49'] = 'HH49'
if 'persns49' in gdf_new_taz.columns:
    rename_map_new['persns49'] = 'PERSNS49'
if 'workrs49' in gdf_new_taz.columns:
    rename_map_new['workrs49'] = 'WORKRS49'
if 'emp49' in gdf_new_taz.columns:
    rename_map_new['emp49']  = 'EMP49'
if rename_map_new:
    gdf_new_taz = gdf_new_taz.rename(columns=rename_map_new)

if 'GEOID20' in gdf_blocks.columns:
    gdf_blocks = gdf_blocks.rename(columns={'GEOID20': 'BLOCK_ID'})

# -----------------------------------------------------------------------------
# 2. Helper Functions
# -----------------------------------------------------------------------------
def split_multipolygons_to_cds(gdf, id_field, ensure_cols=None):
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

    data = {'xs': all_xs, 'ys': all_ys, 'id': all_ids}
    for c in ensure_cols:
        data[c] = attr_data[c]
    return ColumnDataSource(data)

def split_multipolygons_to_text(gdf, id_field):
    """
    Returns a dictionary with centroid coordinates (cx, cy) and the id.
    This is used to add text labels on the map.
    """
    all_cx, all_cy, all_ids = [], [], []
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        row_id = str(row[id_field])
        if geom.geom_type == "MultiPolygon":
            for subpoly in geom.geoms:
                centroid = subpoly.centroid
                all_cx.append(centroid.x)
                all_cy.append(centroid.y)
                all_ids.append(row_id)
        elif geom.geom_type == "Polygon":
            centroid = geom.centroid
            all_cx.append(centroid.x)
            all_cy.append(centroid.y)
            all_ids.append(row_id)
    return {"cx": all_cx, "cy": all_cy, "id": all_ids}

def filter_old_taz(old_id_int):
    # Get the selected TAZ by id (this may return one or more rows)
    subset_old = gdf_old_taz[gdf_old_taz['taz_id'] == old_id_int]
    if subset_old.empty:
        return (None, None, None)
    # Compute the union of the selected TAZ polygons and then the centroid.
    old_union = subset_old.unary_union
    centroid = old_union.centroid
    buffer_radius = 1000  # Use 1 km (1000 m)
    buffer_geom = centroid.buffer(buffer_radius)
    
    # Filter new TAZ and blocks to those that intersect the 1 km buffer.
    new_sub = gdf_new_taz[gdf_new_taz.intersects(buffer_geom)].copy()
    blocks_sub = gdf_blocks[gdf_blocks.intersects(buffer_geom)].copy()
    
    return (subset_old, new_sub, blocks_sub)

def add_sum_row(d, colnames):
    """Append a 'Sum' row even if no items => 0."""
    if 'id' not in d:
        d['id'] = []
        for c in colnames:
            d[c] = []
    sums = {c: 0 for c in colnames}
    for c in colnames:
        for val in d[c]:
            if isinstance(val, (int, float)):
                sums[c] += val
    d['id'].append("Sum")
    for c in colnames:
        d[c].append(sums[c])
    return d

# --- NEW HELPER FUNCTION ---
def add_formatted_fields(source, fields):
    """
    For each field in `fields`, add a new column to source.data with the
    suffix '_fmt' containing the values formatted to 1 decimal.
    """
    for field in fields:
        fmt_field = field + "_fmt"
        # Ensure the field exists in the data
        if field in source.data:
            source.data[fmt_field] = [
                f"{x:.1f}" if isinstance(x, (int, float)) else ""
                for x in source.data[field]
            ]
# -----------------------------------------------------------------------------
# 3. DataSources for the 4 panels and for text labels
# -----------------------------------------------------------------------------
old_taz_source        = ColumnDataSource(dict(xs=[], ys=[], id=[]))
old_taz_blocks_source = ColumnDataSource(dict(xs=[], ys=[], id=[]))

# Include the 2049 fields.
new_taz_source = ColumnDataSource(dict(xs=[], ys=[], id=[], 
                                       HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[], 
                                       HH49=[], PERSNS49=[], WORKRS49=[], EMP49=[]))
# DataSource for additional outlines in panel 2.
new_taz_blocks_source = ColumnDataSource(dict(xs=[], ys=[], id=[]))

blocks_source  = ColumnDataSource(dict(xs=[], ys=[], id=[], 
                                        HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[], 
                                        HH49=[], PERSNS49=[], WORKRS49=[], EMP49=[]))

combined_old_source    = ColumnDataSource(dict(xs=[], ys=[], id=[]))
combined_new_source    = ColumnDataSource(dict(xs=[], ys=[], id=[], 
                                               HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[], 
                                               HH49=[], PERSNS49=[], WORKRS49=[], EMP49=[]))
combined_blocks_source = ColumnDataSource(dict(xs=[], ys=[], id=[]))

# Data source for the 1 km old TAZ buffer (filled polygon)
old_taz_buffer_source = ColumnDataSource(dict(xs=[], ys=[], id=[]))

# Data source for neighbor (all old TAZ outlines intersecting the buffer)
old_taz_neighbors_source = ColumnDataSource(dict(xs=[], ys=[], id=[]))

# Data source for extra old TAZ shapes (to be drawn in light purple)
extra_old_taz_source = ColumnDataSource(dict(xs=[], ys=[], id=[]))

# Data sources for text labels for old and new TAZ IDs.
old_taz_text_source = ColumnDataSource(dict(cx=[], cy=[], id=[]))
new_taz_text_source = ColumnDataSource(dict(cx=[], cy=[], id=[]))
extra_old_taz_text_source = ColumnDataSource(dict(cx=[], cy=[], id=[]))

global_new_gdf    = None
global_blocks_gdf = None

# -----------------------------------------------------------------------------
# 4. Figures (without built-in titles; we add external Divs for the titles)
# -----------------------------------------------------------------------------
TOOLS = "pan,wheel_zoom,box_zoom,reset"

p_old = figure(
    title=None,
    match_aspect=True,
    tools=TOOLS, active_scroll='wheel_zoom',
    x_axis_type="mercator", y_axis_type="mercator",
    sizing_mode="scale_both"
)
p_new = figure(
    title=None,
    match_aspect=True,
    tools=TOOLS + ",tap", active_scroll='wheel_zoom',
    x_axis_type="mercator", y_axis_type="mercator",
    sizing_mode="scale_both"
)
p_combined = figure(
    title=None,
    match_aspect=True,
    tools=TOOLS, active_scroll='wheel_zoom',
    x_axis_type="mercator", y_axis_type="mercator",
    sizing_mode="scale_both"
)
p_blocks = figure(
    title=None,
    match_aspect=True,
    tools=TOOLS + ",tap", active_scroll='wheel_zoom',
    x_axis_type="mercator", y_axis_type="mercator",
    sizing_mode="scale_both"
)

# Create Divs for the titles so they remain visible.
div_old_title      = Div(text="<b>1) Old TAZ (blue)</b>", styles={'font-size': '16px'})
div_new_title      = Div(text="<b>2) New TAZ (red; blocks not selectable)</b>", styles={'font-size': '16px'})
div_combined_title = Div(text="<b>3) Combined (new=red, old=blue, blocks=yellow)</b>", styles={'font-size': '16px'})
div_blocks_title   = Div(text="<b>4) Blocks (selectable, yellow)</b>", styles={'font-size': '16px'})

# Add tile providers.
tile_map = {}
def add_tiles():
    for f in [p_old, p_new, p_combined, p_blocks]:
        tile = f.add_tile(CARTODBPOSITRON)
        tile_map[f] = tile

add_tiles()

# -----------------------------------------------------------------------------
# Apply axis formatting to disable scientific notation and trim trailing zeros.
for f in [p_old, p_new, p_combined, p_blocks]:
    f.xaxis.formatter = NumeralTickFormatter(format="0.2~f")
    f.yaxis.formatter = NumeralTickFormatter(format="0.2~f")

# -----------------------------------------------------------------------------
# 5. Patch Glyphs
# -----------------------------------------------------------------------------
# Panel 1: Draw the old TAZ outlines (blue) with a light fill.
renderer_old_taz = p_old.patches(
    xs="xs", ys="ys",
    source=old_taz_source,
    fill_color="lightblue", fill_alpha=0.3,
    line_color="blue",
    line_width=2
)
p_old.patches(
    xs="xs", ys="ys",
    source=old_taz_blocks_source,
    fill_color=None, line_color="black", line_width=2, line_dash='dotted'
)

# Add a filled 1 km buffer for the old TAZ (non-clickable; used for hover info)
# Changed fill_color to "lightcoral" (light red)
old_taz_buffer_renderer = p_old.patches(
    xs="xs", ys="ys",
    source=old_taz_buffer_source,
    fill_color="lightcoral", fill_alpha=0.3,
    line_color=None
)
# Ensure the buffer is at the bottom so that outlines remain visible:
p_old.renderers.remove(old_taz_buffer_renderer)
p_old.renderers.insert(0, old_taz_buffer_renderer)
# The hover tool for the buffer is removed to avoid default coordinate hover.

# Add neighbor outlines (for all old TAZ features intersecting the buffer)
old_taz_neighbors_renderer = p_old.patches(
    xs="xs", ys="ys",
    source=old_taz_neighbors_source,
    fill_color=None,
    line_color="gray",
    line_width=2,
    line_dash="dotted"
)
p_old.renderers.remove(old_taz_neighbors_renderer)
p_old.renderers.insert(1, old_taz_neighbors_renderer)

# Draw extra old TAZ shapes in light purple.
renderer_extra_old_taz = p_old.patches(
    xs="xs", ys="ys",
    source=extra_old_taz_source,
    fill_color="#E6E6FA", fill_alpha=0.3,
    line_color="purple", line_width=2
)
# Add a hover tool for the old TAZ and extra old TAZ outlines.
hover_old_patches = HoverTool(tooltips=[("Old TAZ ID", "@id")],
                              renderers=[renderer_old_taz, renderer_extra_old_taz])
p_old.add_tools(hover_old_patches)

# Panel 2: New TAZ – red boundary with yellow fill on selection.
taz_glyph_new = p_new.patches(
    xs="xs", ys="ys",
    source=new_taz_source,
    fill_color=None,
    line_color="red", line_width=2,
    selection_fill_color="yellow", selection_fill_alpha=0.3,
    selection_line_color="red", selection_line_width=2,
    nonselection_fill_color=None, nonselection_line_color="red"
)
p_new.patches(
    xs="xs", ys="ys",
    source=new_taz_blocks_source,
    fill_color=None, line_color="black", line_width=2, line_dash='dotted'
)
# Updated hover tool for p_new using the pre-formatted fields.
p_new.add_tools(HoverTool(
    tooltips=[
        ("TAZ ID", "@id"),
        ("HH19", "@HH19_fmt"),
        ("EMP19", "@EMP19_fmt"),
        ("HH49", "@HH49_fmt"),
        ("EMP49", "@EMP49_fmt")
    ],
    renderers=[taz_glyph_new]
))

# Panel 3: Combined – new TAZ first, then old TAZ, then blocks on top.
p_combined.patches(
    xs="xs", ys="ys",
    source=combined_new_source,
    fill_color=None, line_color="red", line_width=2
)
p_combined.patches(
    xs="xs", ys="ys",
    source=combined_old_source,
    fill_color=None, line_color="blue", line_width=2
)
p_combined.patches(
    xs="xs", ys="ys",
    source=combined_blocks_source,
    fill_color="yellow", fill_alpha=0.3,
    line_color="black", line_width=2, line_dash='dotted'
)

# Panel 4: Blocks – yellow fill with black dotted border on selection.
renderer_blocks = p_blocks.patches(
    xs="xs", ys="ys",
    source=blocks_source,
    fill_color="yellow", fill_alpha=0.3,
    line_color="black", line_width=2, line_dash='dotted', line_alpha=0.85,
    selection_fill_color="yellow", selection_fill_alpha=0.3,
    selection_line_color="black", selection_line_dash='dotted',
    nonselection_fill_alpha=0.10, nonselection_line_color="black",
    nonselection_line_dash='dotted', nonselection_line_alpha=0.85
)
p_blocks.add_tools(HoverTool(
    tooltips=[
        ("Block ID", "@id"),
        ("HH19", "@HH19_fmt"),
        ("EMP19", "@EMP19_fmt"),
        ("HH49", "@HH49_fmt"),
        ("EMP49", "@EMP49_fmt")
    ],
    renderers=[renderer_blocks]
))

# Extra old TAZ glyphs (light purple) added to panels 1 and 3.
p_old.patches(
    xs="xs", ys="ys",
    source=extra_old_taz_source,
    fill_color="#E6E6FA", fill_alpha=0.3,
    line_color="purple", line_width=2
)

p_combined.patches(
    xs="xs", ys="ys",
    source=extra_old_taz_source,
    fill_color="#E6E6FA", fill_alpha=0.3,
    line_color="purple", line_width=2
)

# Add text glyphs to show TAZ IDs on the top panels.
p_old.text(x="cx", y="cy", text="id", source=old_taz_text_source,
           text_color="blue", text_font_size="10pt", text_font_style="bold",
           text_align="center", text_baseline="middle")
p_old.text(x="cx", y="cy", text="id", source=extra_old_taz_text_source,
           text_color="blue", text_font_size="10pt", text_font_style="bold",
           text_align="center", text_baseline="middle")
p_new.text(x="cx", y="cy", text="id", source=new_taz_text_source,
           text_color="red", text_font_size="10pt", text_font_style="bold",
           text_align="center", text_baseline="middle")

# -----------------------------------------------------------------------------
# 6. Tables with persistent Sum row (including 49 data columns)
# -----------------------------------------------------------------------------
sum_template = """
<% if (id == 'Sum') { %>
<b><%= value %></b>
<% } else { %>
<%= value %>
<% } %>
"""
bold_formatter = HTMLTemplateFormatter(template=sum_template)
table_cols = [
    TableColumn(field="id",         title="ID",         formatter=bold_formatter, width=40),
    TableColumn(field="HH19",       title="HH19",       formatter=bold_formatter, width=70),
    TableColumn(field="PERSNS19",   title="PERSNS19",   formatter=bold_formatter, width=70),
    TableColumn(field="WORKRS19",   title="WORKRS19",   formatter=bold_formatter, width=70),
    TableColumn(field="EMP19",      title="EMP19",      formatter=bold_formatter, width=70),
    TableColumn(field="HH49",       title="HH49",       formatter=bold_formatter, width=70),
    TableColumn(field="PERSNS49",   title="PERSNS49",   formatter=bold_formatter, width=70),
    TableColumn(field="WORKRS49",   title="WORKRS49",   formatter=bold_formatter, width=70),
    TableColumn(field="EMP49",      title="EMP49",      formatter=bold_formatter, width=70),
]

new_taz_table_source = ColumnDataSource(dict(id=[], 
                                              HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[], 
                                              HH49=[], PERSNS49=[], WORKRS49=[], EMP49=[]))
blocks_table_source  = ColumnDataSource(dict(id=[], 
                                              HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[], 
                                              HH49=[], PERSNS49=[], WORKRS49=[], EMP49=[]))

new_taz_data_table = DataTable(source=new_taz_table_source, columns=table_cols, width=550, height=300, fit_columns=False)
blocks_data_table  = DataTable(source=blocks_table_source,  columns=table_cols, width=550, height=300, fit_columns=False)

def update_new_taz_table():
    inds = new_taz_source.selected.indices
    d = {"id":[], "HH19":[], "PERSNS19":[], "WORKRS19":[], "EMP19":[],
         "HH49":[], "PERSNS49":[], "WORKRS49":[], "EMP49":[]}
    if inds:
        for c in d.keys():
            if c in new_taz_source.data:
                d[c] = [new_taz_source.data[c][i] for i in inds]
    d = add_sum_row(d, ["HH19","PERSNS19","WORKRS19","EMP19", "HH49","PERSNS49","WORKRS49","EMP49"])
    new_taz_table_source.data = d

def update_blocks_table():
    inds = blocks_source.selected.indices
    d = {"id":[], "HH19":[], "PERSNS19":[], "WORKRS19":[], "EMP19":[],
         "HH49":[], "PERSNS49":[], "WORKRS49":[], "EMP49":[]}
    if inds:
        for c in d.keys():
            d[c] = [blocks_source.data[c][i] for i in inds]
    d = add_sum_row(d, ["HH19","PERSNS19","WORKRS19","EMP19", "HH49","PERSNS49","WORKRS49","EMP49"])
    blocks_table_source.data = d

new_taz_source.selected.on_change("indices", lambda attr, old, new: update_new_taz_table())
blocks_source.selected.on_change("indices", lambda attr, old, new: update_blocks_table())

# -----------------------------------------------------------------------------
# 7. UI: Text input, search, match zoom, tile select, etc.
# -----------------------------------------------------------------------------
search_label = Div(text="Currently Searching TAZ: <span style='color:green'>(none)</span>", width=300)
label_taz    = Div(text="<b>Enter Old TAZ ID:</b>", width=120)
text_input   = TextInput(value="", title="", placeholder="TAZ ID...", width=100)
search_button= Button(label="Search TAZ", button_type="success", width=80)
match_zoom_btn = Button(label="Match 1st Panel Zoom", width=130)

# Extra TAZ search for purple shapes.
extra_taz_label = Div(text="<b>Extra TAZ IDs (comma separated):</b>", width=200)
extra_taz_input = TextInput(value="", title="", placeholder="e.g. 101, 102, 103", width=150)
extra_search_button = Button(label="Search Extra TAZ", button_type="primary", width=120)

tile_label   = Div(text="<b>Selected Map Background:</b>", width=150)
tile_select  = Select(value="CartoDB Positron", options=["CartoDB Positron","ESRI Satellite"], width=140)

def run_search():
    val = text_input.value.strip()
    if not val:
        search_label.text = "Currently Searching TAZ: <span style='color:red'>(no input)</span>"
        return
    try:
        old_id_int = int(val)
    except ValueError:
        search_label.text = "Currently Searching TAZ: <span style='color:red'>[TAZ Not Found]</span>"
        return

    o, n, b = filter_old_taz(old_id_int)
    if o is None or o.empty:
        search_label.text = "Currently Searching TAZ: <span style='color:red'>[TAZ Not Found]</span>"
        return

    search_label.text = f"Currently Searching TAZ: <span style='color:green'>{old_id_int}</span>"

    global global_new_gdf, global_blocks_gdf
    global_new_gdf    = n
    global_blocks_gdf = b

    # Compute the 1 km buffer based on the selected old TAZ union.
    old_union = o.unary_union
    centroid = old_union.centroid
    buffer_geom = centroid.buffer(1000)  # 1 km radius

    # Update the old TAZ buffer data.
    xs_buffer, ys_buffer = buffer_geom.exterior.coords.xy
    old_taz_buffer_source.data = {
        "xs": [list(xs_buffer)],
        "ys": [list(ys_buffer)],
        "id": [str(old_id_int)]
    }

    # Update neighbor outlines to show all old TAZes intersecting the buffer.
    neighbors = gdf_old_taz[gdf_old_taz.intersects(buffer_geom)].copy()
    neighbors_temp = split_multipolygons_to_cds(neighbors, "taz_id")
    old_taz_neighbors_source.data = dict(neighbors_temp.data)

    old_temp = split_multipolygons_to_cds(o, "taz_id")
    new_temp = split_multipolygons_to_cds(n, "taz_id", 
                                          ["HH19", "PERSNS19", "WORKRS19", "EMP19",
                                           "HH49", "PERSNS49", "WORKRS49", "EMP49"])
    blocks_temp = split_multipolygons_to_cds(b, "BLOCK_ID", 
                                             ["HH19", "PERSNS19", "WORKRS19", "EMP19",
                                              "HH49", "PERSNS49", "WORKRS49", "EMP49"])

    old_blocks_temp = split_multipolygons_to_cds(b, "BLOCK_ID")
    new_blocks_temp = split_multipolygons_to_cds(b, "BLOCK_ID")
    comb_old_temp   = old_temp
    comb_new_temp   = new_temp
    comb_blocks_temp = split_multipolygons_to_cds(b, "BLOCK_ID")

    # --- Pre-format numeric values to 1 decimal ---
    add_formatted_fields(new_temp, ["HH19", "EMP19", "HH49", "EMP49"])
    add_formatted_fields(blocks_temp, ["HH19", "EMP19", "HH49", "EMP49"])
    
    old_taz_source.data         = dict(old_temp.data)
    new_taz_source.data         = dict(new_temp.data)
    blocks_source.data          = dict(blocks_temp.data)
    old_taz_blocks_source.data  = dict(old_blocks_temp.data)
    new_taz_blocks_source.data  = dict(new_blocks_temp.data)
    combined_old_source.data    = dict(comb_old_temp.data)
    combined_new_source.data    = dict(comb_new_temp.data)
    combined_blocks_source.data = dict(comb_blocks_temp.data)

    # Update text labels for old and new TAZ in the top panels.
    old_text_data = split_multipolygons_to_text(o, "taz_id")
    old_taz_text_source.data = old_text_data

    new_text_data = split_multipolygons_to_text(n, "taz_id")
    new_taz_text_source.data = new_text_data

    # Clear tables & selection.
    new_taz_source.selected.indices = []
    blocks_source.selected.indices  = []
    new_taz_table_source.data = dict()
    blocks_table_source.data  = dict()
    update_new_taz_table()
    update_blocks_table()

    # Zoom panel 1 to the bounds of the selected old TAZ (with a little extra margin).
    minx, miny, maxx, maxy = o.total_bounds
    if minx == maxx or miny == maxy:
        minx -= 1000; maxx += 1000
        miny -= 1000; maxy += 1000
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

    # Auto-match all 4 panels to the same bounding box.
    for p in [p_new, p_combined, p_blocks]:
        p.x_range.start = minx
        p.x_range.end = maxx
        p.y_range.start = miny
        p.y_range.end = maxy

def on_search_click():
    run_search()

search_button.on_click(on_search_click)

def on_text_input_change(attr, old, new):
    # Trigger search when Enter is pressed.
    run_search()

text_input.on_change("value", on_text_input_change)

def on_tile_select_change(attr, old, new):
    if new == "CartoDB Positron":
        provider = CARTODBPOSITRON
    else:
        provider = ESRI_IMAGERY
    for fig_ in [p_old, p_new, p_combined, p_blocks]:
        old_tile = tile_map.get(fig_)
        if old_tile and old_tile in fig_.renderers:
            fig_.renderers.remove(old_tile)
        new_t = fig_.add_tile(provider)
        tile_map[fig_] = new_t

tile_select.on_change("value", on_tile_select_change)

def on_match_zoom_click():
    # Copy p_old's range to the other panels.
    for p in [p_new, p_combined, p_blocks]:
        p.x_range.start = p_old.x_range.start
        p.x_range.end   = p_old.x_range.end
        p.y_range.start = p_old.y_range.start
        p.y_range.end   = p_old.y_range.end

match_zoom_btn.on_click(on_match_zoom_click)

# Extra TAZ Search Callback: Update extra_old_taz_source and its text labels from comma-delimited IDs.
def run_extra_search():
    val = extra_taz_input.value.strip()
    if not val:
        extra_old_taz_source.data = {"xs": [], "ys": [], "id": []}
        extra_old_taz_text_source.data = {"cx": [], "cy": [], "id": []}
        return
    try:
        # Parse the comma-separated IDs (assumed to be integers)
        id_list = [int(x.strip()) for x in val.split(",") if x.strip() != ""]
    except ValueError:
        extra_old_taz_source.data = {"xs": [], "ys": [], "id": []}
        extra_old_taz_text_source.data = {"cx": [], "cy": [], "id": []}
        return
    subset_extra = gdf_old_taz[gdf_old_taz['taz_id'].isin(id_list)]
    if subset_extra.empty:
        extra_old_taz_source.data = {"xs": [], "ys": [], "id": []}
        extra_old_taz_text_source.data = {"cx": [], "cy": [], "id": []}
        return
    extra_cdsrc = split_multipolygons_to_cds(subset_extra, "taz_id")
    extra_old_taz_source.data = dict(extra_cdsrc.data)
    extra_text_data = split_multipolygons_to_text(subset_extra, "taz_id")
    extra_old_taz_text_source.data = extra_text_data

extra_search_button.on_click(run_extra_search)
# Also trigger extra search when the user presses Enter/Tab in the extra search input.
extra_taz_input.on_change("value_input", lambda attr, old, new: run_extra_search())

# -----------------------------------------------------------------------------
# 9. Layout
# -----------------------------------------------------------------------------
row1_left = row(
    label_taz, text_input, Spacer(width=10),
    extra_taz_label, extra_taz_input, extra_search_button
)
row1_center = row(search_label)
row1_right = row(Div(text="<b>Selected Map Background:</b>", width=150), tile_select)

row1 = row(row1_left, Spacer(width=50), row1_center, Spacer(width=50), row1_right, sizing_mode="stretch_width")
row2 = row(search_button, match_zoom_btn, sizing_mode="stretch_width")

top_maps = row(
    column(div_old_title, p_old, sizing_mode="scale_both"),
    column(div_new_title, p_new, sizing_mode="scale_both"),
    sizing_mode="scale_both"
)
bot_maps = row(
    column(div_combined_title, p_combined, sizing_mode="scale_both"),
    column(div_blocks_title, p_blocks, sizing_mode="scale_both"),
    sizing_mode="scale_both"
)
maps_col = column(top_maps, bot_maps, sizing_mode="stretch_both")

top_table = column(Div(text="<b>New TAZ Table</b>"), new_taz_data_table, sizing_mode="scale_both")
bot_table = column(Div(text="<b>Blocks Table</b>"),  blocks_data_table, sizing_mode="scale_both")
tables_col = column(
    top_table, 
    bot_table, 
    width_policy="max",  
    sizing_mode="stretch_both",  
    min_width=100,  
    max_width=375  
)

main_row = row(maps_col, tables_col, sizing_mode="stretch_both")
layout_final = column(row1, row2, main_row, sizing_mode="stretch_both")

curdoc().add_root(layout_final)
curdoc().title = "Final Layout - No doc.stylesheets - Bokeh 3.x"
