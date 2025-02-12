import os, glob
import geopandas as gpd
from shapely.geometry import Polygon, MultiPolygon
import numpy as np

from bokeh.io import curdoc
from bokeh.layouts import column, row, Spacer
from bokeh.models import (
    ColumnDataSource, DataTable, TableColumn,
    Div, TextInput, Button, Select, HoverTool,
    CustomJS, NumeralTickFormatter, ResetTool,
    CrosshairTool
)
from bokeh.models.widgets.tables import HTMLTemplateFormatter
from bokeh.plotting import figure
from bokeh.tile_providers import CARTODBPOSITRON, ESRI_IMAGERY

# -----------------------------------------------------------------------------
# 1) Read Shapefiles
# -----------------------------------------------------------------------------
old_taz_folder = "./shapefiles/old_taz_shapefile"
new_taz_folder = "./shapefiles/new_taz_shapefile"
blocks_folder  = "./shapefiles/blocks_shapefile"

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

# Convert to EPSG:3857 if needed
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
# 2) Helper Functions
# -----------------------------------------------------------------------------
def split_multipolygons_to_cds(gdf, id_field, ensure_cols=None):
    """
    Break multi-polygons into single polygon ring coordinate lists
    for Bokeh's patches glyph.
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
    Return centroid coordinates for each (multi)polygon for text labeling.
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

def add_sum_row(d, colnames):
    """
    Append a 'Sum' row for the DataTable's numeric fields.
    """
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

def add_formatted_fields(source, fields):
    """
    Add *_fmt columns for nicer display in hover tooltips.
    """
    for field in fields:
        fmt_field = field + "_fmt"
        if field in source.data:
            source.data[fmt_field] = [
                f"{x:.1f}" if isinstance(x, (int, float)) else ""
                for x in source.data[field]
            ]

# -----------------------------------------------------------------------------
# 3) DataSources
# -----------------------------------------------------------------------------
old_taz_source        = ColumnDataSource(dict(xs=[], ys=[], id=[]))
old_taz_blocks_source = ColumnDataSource(dict(xs=[], ys=[], id=[]))
new_taz_source        = ColumnDataSource(dict(xs=[], ys=[], id=[],
                                              HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[],
                                              HH49=[], PERSNS49=[], WORKRS49=[], EMP49=[]))
new_taz_blocks_source = ColumnDataSource(dict(xs=[], ys=[], id=[]))
blocks_source         = ColumnDataSource(dict(xs=[], ys=[], id=[],
                                              HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[],
                                              HH49=[], PERSNS49=[], WORKRS49=[], EMP49=[]))

combined_old_source    = ColumnDataSource(dict(xs=[], ys=[], id=[]))
combined_new_source    = ColumnDataSource(dict(xs=[], ys=[], id=[],
                                               HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[],
                                               HH49=[], PERSNS49=[], WORKRS49=[], EMP49=[]))
combined_blocks_source = ColumnDataSource(dict(xs=[], ys=[], id=[]))

old_taz_buffer_source    = ColumnDataSource(dict(xs=[], ys=[], id=[]))
old_taz_neighbors_source = ColumnDataSource(dict(xs=[], ys=[], id=[]))
extra_old_taz_source     = ColumnDataSource(dict(xs=[], ys=[], id=[]))

old_taz_text_source      = ColumnDataSource(dict(cx=[], cy=[], id=[]))
# Note: new_taz_text_source now includes a "color" field for dynamic text color.
new_taz_text_source      = ColumnDataSource(dict(cx=[], cy=[], id=[], color=[]))
extra_old_taz_text_source= ColumnDataSource(dict(cx=[], cy=[], id=[]))

centroid_source          = ColumnDataSource(data={'cx': [], 'cy': []})

# -----------------------------------------------------------------------------
# 4) Figures
# -----------------------------------------------------------------------------
TOOLS = "pan,wheel_zoom,box_zoom,reset"

p_old = figure(
    match_aspect=True, tools=TOOLS, active_scroll='wheel_zoom',
    x_axis_type="mercator", y_axis_type="mercator",
    sizing_mode="scale_both"
)

# Top‐right panel: add ",tap" + crosshair
crosshair_top = CrosshairTool(line_alpha=0.8, line_color="red")
p_new = figure(
    match_aspect=True, tools=TOOLS + ",tap", active_scroll='wheel_zoom',
    x_axis_type="mercator", y_axis_type="mercator",
    sizing_mode="scale_both"
)
p_new.add_tools(crosshair_top)
p_new.toolbar.active_inspect = crosshair_top

# Bottom‐left panel
p_combined = figure(
    match_aspect=True, tools=TOOLS, active_scroll='wheel_zoom',
    x_axis_type="mercator", y_axis_type="mercator",
    sizing_mode="scale_both"
)

# Bottom‐right panel: add ",tap" + crosshair
crosshair_bot = CrosshairTool(line_alpha=0.8, line_color="red")
p_blocks = figure(
    match_aspect=True, tools=TOOLS + ",tap", active_scroll='wheel_zoom',
    x_axis_type="mercator", y_axis_type="mercator",
    sizing_mode="scale_both"
)
p_blocks.add_tools(crosshair_bot)
p_blocks.toolbar.active_inspect = crosshair_bot

# Titles
div_old_title      = Div(text="<b>1) Old TAZ (green IDs)</b>", styles={'font-size': '16px'})
div_new_title      = Div(text="<b>2) New TAZ (red outlines)</b>", styles={'font-size': '16px'})
div_combined_title = Div(text="<b>3) Combined (new=red, old=green, blocks=yellow)</b>", styles={'font-size': '16px'})
div_blocks_title   = Div(text="<b>4) Blocks (selectable, yellow)</b>", styles={'font-size': '16px'})

# -----------------------------------------------------------------------------
# 5) Add Base Tiles
# -----------------------------------------------------------------------------
tile_map = {}
for f in [p_old, p_new, p_combined, p_blocks]:
    t = f.add_tile(CARTODBPOSITRON)
    tile_map[f] = t

# Grab references to each figure’s ResetTool (not used anymore)
p_old_reset, p_new_reset, p_comb_reset, p_blocks_reset = None, None, None, None
for t in p_old.toolbar.tools:
    if isinstance(t, ResetTool):
        p_old_reset = t
for t in p_new.toolbar.tools:
    if isinstance(t, ResetTool):
        p_new_reset = t
for t in p_combined.toolbar.tools:
    if isinstance(t, ResetTool):
        p_comb_reset = t
for t in p_blocks.toolbar.tools:
    if isinstance(t, ResetTool):
        p_blocks_reset = t

# -----------------------------------------------------------------------------
# 6) Patch Glyphs
# -----------------------------------------------------------------------------
# Old TAZ
renderer_old_taz = p_old.patches(
    xs="xs", ys="ys", source=old_taz_source,
    fill_color="lightgreen", fill_alpha=0.3,
    line_color="green", line_width=2
)
# Make block boundaries very faint (non-selectable) in top left
p_old.patches(
    xs="xs", ys="ys", source=old_taz_blocks_source,
    fill_color=None, line_color="black", line_width=2, line_dash='dotted',
    line_alpha=0.4
)
buffer_renderer = p_old.patches(
    xs="xs", ys="ys", source=old_taz_buffer_source,
    fill_color="lightyellow", fill_alpha=0.5,  # Increased alpha for stronger yellow background
    line_color=None
)
p_old.renderers.remove(buffer_renderer)
p_old.renderers.insert(0, buffer_renderer)

neighbors_renderer = p_old.patches(
    xs="xs", ys="ys", source=old_taz_neighbors_source,
    fill_color=None, line_color="gray", line_width=2, line_dash="dotted"
)
p_old.renderers.remove(neighbors_renderer)
p_old.renderers.insert(1, neighbors_renderer)

renderer_extra_old_taz = p_old.patches(
    xs="xs", ys="ys", source=extra_old_taz_source,
    fill_color="#E6E6FA", fill_alpha=0.3,
    line_color="purple", line_width=2
)

hover_old_patches = HoverTool(
    tooltips=[("Old TAZ ID", "@id")],
    renderers=[renderer_old_taz, renderer_extra_old_taz]
)
p_old.add_tools(hover_old_patches)

# New TAZ (top‐right)
taz_glyph_new = p_new.patches(
    xs="xs", ys="ys", source=new_taz_source,
    fill_color=None, line_color="red", line_width=2,
    selection_fill_color="yellow", selection_fill_alpha=0.3,
    selection_line_color="red", selection_line_dash='solid',
    # Make non-selected boundaries more transparent:
    nonselection_fill_alpha=0.10, nonselection_line_color="red",
    nonselection_line_dash='dotted', nonselection_line_alpha=0.3
)
# Make block boundaries very faint (non-selectable) in top right
p_new.patches(
    xs="xs", ys="ys", source=new_taz_blocks_source,
    fill_color=None, line_color="black", line_width=2, line_dash='dotted',
    line_alpha=0.4
)
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

# Combined (bottom‐left)
p_combined.patches(
    xs="xs", ys="ys", source=combined_new_source,
    fill_color=None, line_color="red", line_width=2
)
# Thicken the green old TAZ boundaries so they are easier to see:
p_combined.patches(
    xs="xs", ys="ys", source=combined_old_source,
    fill_color=None, line_color="green", line_width=3
)
p_combined.patches(
    xs="xs", ys="ys", source=combined_blocks_source,
    fill_color="yellow", fill_alpha=0.3,
    line_color="black", line_width=2, line_dash='dotted'
)
p_combined.patches(
    xs="xs", ys="ys", source=extra_old_taz_source,
    fill_color="#E6E6FA", fill_alpha=0.3,
    line_color="purple", line_width=2
)

# Blocks (bottom‐right)
renderer_blocks = p_blocks.patches(
    xs="xs", ys="ys", source=blocks_source,
    fill_color="yellow", fill_alpha=0.3,
    line_color="black", line_width=2, line_dash='dotted', line_alpha=0.85,
    selection_fill_color="yellow", selection_fill_alpha=0.3,
    # Change selected blocks to have a solid boundary:
    selection_line_color="black", selection_line_dash="solid",
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

# -----------------------------------------------------------------------------
# 7) Text Labels
# -----------------------------------------------------------------------------
p_old.text(
    x="cx", y="cy", text="id", source=old_taz_text_source,
    text_color="green", text_font_size="10pt", text_font_style="bold",
    text_align="center", text_baseline="middle"
)
p_old.text(
    x="cx", y="cy", text="id", source=extra_old_taz_text_source,
    text_color="purple", text_font_size="10pt", text_font_style="bold",
    text_align="center", text_baseline="middle"
)
# For top-right TAZ IDs, use the dynamic "color" field so that only selected IDs are strong red.
p_new.text(
    x="cx", y="cy", text="id", source=new_taz_text_source,
    text_color={'field': 'color'}, text_font_size="10pt", text_font_style="bold",
    text_align="center", text_baseline="middle"
)

# -----------------------------------------------------------------------------
# 8) Data Tables with Sum Row
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
    TableColumn(field="id",       title="ID",       formatter=bold_formatter, width=40),
    TableColumn(field="HH19",     title="HH19",     formatter=bold_formatter, width=70),
    TableColumn(field="PERSNS19", title="PERSNS19", formatter=bold_formatter, width=70),
    TableColumn(field="WORKRS19", title="WORKRS19", formatter=bold_formatter, width=70),
    TableColumn(field="EMP19",    title="EMP19",    formatter=bold_formatter, width=70),
    TableColumn(field="HH49",     title="HH49",     formatter=bold_formatter, width=70),
    TableColumn(field="PERSNS49", title="PERSNS49", formatter=bold_formatter, width=70),
    TableColumn(field="WORKRS49", title="WORKRS49", formatter=bold_formatter, width=70),
    TableColumn(field="EMP49",    title="EMP49",    formatter=bold_formatter, width=70),
]

new_taz_table_source = ColumnDataSource(dict(
    id=[], HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[],
    HH49=[], PERSNS49=[], WORKRS49=[], EMP49=[]
))
blocks_table_source  = ColumnDataSource(dict(
    id=[], HH19=[], PERSNS19=[], WORKRS19=[], EMP19=[],
    HH49=[], PERSNS49=[], WORKRS49=[], EMP49=[]
))

new_taz_data_table = DataTable(
    source=new_taz_table_source,
    columns=table_cols,
    fit_columns=False,
    sizing_mode="stretch_both"
)
blocks_data_table  = DataTable(
    source=blocks_table_source,
    columns=table_cols,
    fit_columns=False,
    sizing_mode="stretch_both"
)

def add_sum_to_new_taz_table():
    inds = new_taz_source.selected.indices
    d = {
        "id": [], "HH19": [], "PERSNS19": [], "WORKRS19": [], "EMP19": [],
        "HH49": [], "PERSNS49": [], "WORKRS49": [], "EMP49": []
    }
    if inds:
        for c in d.keys():
            if c in new_taz_source.data:
                d[c] = [new_taz_source.data[c][i] for i in inds]
    d = add_sum_row(d, ["HH19","PERSNS19","WORKRS19","EMP19","HH49","PERSNS49","WORKRS49","EMP49"])
    new_taz_table_source.data = d

def add_sum_to_blocks_table():
    inds = blocks_source.selected.indices
    d = {
        "id": [], "HH19": [], "PERSNS19": [], "WORKRS19": [], "EMP19": [],
        "HH49": [], "PERSNS49": [], "WORKRS49": [], "EMP49": []
    }
    if inds:
        for c in d.keys():
            d[c] = [blocks_source.data[c][i] for i in inds]
    d = add_sum_row(d, ["HH19","PERSNS19","WORKRS19","EMP19","HH49","PERSNS49","WORKRS49","EMP49"])
    blocks_table_source.data = d

# Whenever a selection changes in top‐right (new TAZ) or bottom‐right (blocks), update tables
new_taz_source.selected.on_change("indices", lambda attr, old, new: add_sum_to_new_taz_table())
blocks_source.selected.on_change("indices",  lambda attr, old, new: add_sum_to_blocks_table())

# -----------------------------------------------------------------------------
# 9) Additional UI & Buttons
# -----------------------------------------------------------------------------
curdoc().add_root(Div(text="""
<style>
.my-green-button .bk-btn {
    background-color: green !important;
    color: white !important;
}
</style>
""", visible=False))

def create_divider(height="25px"):
    return Div(text="", styles={"border-left": "1px solid #ccc", "height": height, "margin": "0 10px"})

search_label = Div(text="<b>Currently Searching TAZ: <span style='color:green'>(none)</span></b>", width=220)
extra_taz_label = Div(text="<b>Extra TAZ IDs (comma separated):</b>", width=150)
extra_taz_input = TextInput(value="", title="", placeholder="e.g. 101, 102, 103", width=160)
extra_search_button = Button(label="Search Extra TAZ", button_type='success', width=120)
extra_search_button.css_classes.append("my-green-button")

label_taz = Div(text="<b>Enter Old TAZ ID:</b>", width=100)
text_input = TextInput(value="", title="", placeholder="TAZ ID...", width=100)
search_button = Button(label="Search TAZ", button_type='success', width=80)
search_button.css_classes.append("my-green-button")

tile_label = Div(text="<b>Selected Map Background:</b>", width=120)
tile_select = Select(value="CartoDB Positron", options=["CartoDB Positron","ESRI Satellite"], width=140)

radius_label = Div(text="<b>Buffer Radius (m):</b>", width=120)
radius_input = TextInput(value="1000", title="", placeholder="e.g. 1000", width=80)
apply_radius_button = Button(label="Apply Radius", button_type='success', width=80)
apply_radius_button.css_classes.append("my-green-button")

# Group row1: left side
group_left = row(label_taz, text_input, search_button)
# Extra TAZ
group_extra  = row(extra_taz_label, extra_taz_input, extra_search_button)
# Right side
group_right  = row(tile_label, tile_select, # create_divider(),
                   radius_label, radius_input, apply_radius_button)

row1_combined = row(group_left, group_extra, group_right, sizing_mode="stretch_width")

# Second row: GMaps, match zoom, then "Currently Searching TAZ"
open_gmaps_button = Button(label="Open TAZ in Google Maps", button_type="warning", width=150)
open_gmaps_button.js_on_click(CustomJS(args=dict(centroid_source=centroid_source), code="""
    var data = centroid_source.data;
    if (data['cx'].length === 0 || data['cy'].length === 0) {
        alert("No TAZ centroid available. Please perform a search first.");
        return;
    }
    var x = data['cx'][0];
    var y = data['cy'][0];
    // Convert from Web Mercator to lat/lon
    var R = 6378137.0;
    var lon = (x / R) * (180 / Math.PI);
    var lat = (Math.PI / 2 - 2 * Math.atan(Math.exp(-y / R))) * (180 / Math.PI);
    var url = "https://www.google.com/maps?q=" + lat + "," + lon;
    window.open(url, "_blank");
"""))

match_zoom_btn = Button(label="Match 1st Panel Zoom", button_type="primary", width=130)
# Removed the Reset Views button and its callback

def on_match_zoom_click():
    # Copy p_old's range to the other three
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

row2 = row(
    open_gmaps_button,
    match_zoom_btn,
    search_label,  # Moved "Currently Searching TAZ" here
    sizing_mode="stretch_width"
)

# -----------------------------------------------------------------------------
# 10) Searching Logic
# -----------------------------------------------------------------------------
def run_search():
    val = text_input.value.strip()
    if not val:
        search_label.text = "<b>Currently Searching TAZ: <span style='color:green'>(none)</span></b>"
        return

    try:
        old_id_int = int(val)
    except ValueError:
        search_label.text = "<b>Currently Searching TAZ: <span style='color:red'>[Invalid ID]</span></b>"
        return

    # Get radius
    try:
        radius = float(radius_input.value.strip())
        if radius <= 0:
            radius = 1000
    except ValueError:
        radius = 1000
        radius_input.value = "1000"

    subset_old = gdf_old_taz[gdf_old_taz['taz_id'] == old_id_int]
    if subset_old.empty:
        search_label.text = "<b>Currently Searching TAZ: <span style='color:red'>[Not Found]</span></b>"
        return

    search_label.text = f"<b>Currently Searching TAZ: <span style='color:green'>{old_id_int}</span></b>"
    old_union = subset_old.unary_union
    centroid = old_union.centroid
    centroid_source.data = {"cx": [centroid.x], "cy": [centroid.y]}

    # Build buffer
    buffer_geom = centroid.buffer(radius)
    if (not buffer_geom.is_empty) and buffer_geom.geom_type == "Polygon":
        bx, by = buffer_geom.exterior.coords.xy
        old_taz_buffer_source.data = {"xs": [list(bx)], "ys": [list(by)], "id": [str(old_id_int)]}
    else:
        old_taz_buffer_source.data = {"xs": [], "ys": [], "id": []}

    neighbors = gdf_old_taz[gdf_old_taz.intersects(buffer_geom)].copy()
    neighbors_temp = split_multipolygons_to_cds(neighbors, "taz_id")
    old_taz_neighbors_source.data = dict(neighbors_temp.data)

    new_sub    = gdf_new_taz[gdf_new_taz.intersects(buffer_geom)].copy()
    blocks_sub = gdf_blocks[gdf_blocks.intersects(buffer_geom)].copy()

    old_temp  = split_multipolygons_to_cds(subset_old, "taz_id")
    new_temp  = split_multipolygons_to_cds(new_sub, "taz_id",
                                           ["HH19","PERSNS19","WORKRS19","EMP19",
                                            "HH49","PERSNS49","WORKRS49","EMP49"])
    blocks_temp = split_multipolygons_to_cds(blocks_sub, "BLOCK_ID",
                                             ["HH19","PERSNS19","WORKRS19","EMP19",
                                              "HH49","PERSNS49","WORKRS49","EMP49"])
    old_blk_temp = split_multipolygons_to_cds(blocks_sub, "BLOCK_ID")
    new_blk_temp = split_multipolygons_to_cds(blocks_sub, "BLOCK_ID")

    comb_old_temp = old_temp
    comb_new_temp = new_temp
    comb_blk_temp = split_multipolygons_to_cds(blocks_sub, "BLOCK_ID")

    add_formatted_fields(new_temp,    ["HH19","EMP19","HH49","EMP49"])
    add_formatted_fields(blocks_temp, ["HH19","EMP19","HH49","EMP49"])

    old_taz_source.data          = dict(old_temp.data)
    new_taz_source.data          = dict(new_temp.data)
    blocks_source.data           = dict(blocks_temp.data)
    old_taz_blocks_source.data   = dict(old_blk_temp.data)
    new_taz_blocks_source.data   = dict(new_blk_temp.data)
    combined_old_source.data     = dict(comb_old_temp.data)
    combined_new_source.data     = dict(comb_new_temp.data)
    combined_blocks_source.data  = dict(comb_blk_temp.data)

    # Label coords
    old_taz_text_source.data = split_multipolygons_to_text(subset_old, "taz_id")
    new_taz_text_source.data = split_multipolygons_to_text(new_sub,   "taz_id")
    # Initialize text color for top-right TAZ IDs (all start faint)
    default_colors = ["rgba(0,0,0,0.3)"] * len(new_taz_text_source.data['id'])
    new_taz_text_source.data['color'] = default_colors

    # Clear selections + tables
    new_taz_source.selected.indices = []
    blocks_source.selected.indices  = []
    new_taz_table_source.data = {}
    blocks_table_source.data  = {}
    add_sum_to_new_taz_table()
    add_sum_to_blocks_table()

    # Zoom
    minx, miny, maxx, maxy = subset_old.total_bounds
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

    for p in [p_old, p_new, p_combined, p_blocks]:
        p.x_range.start = minx
        p.x_range.end   = maxx
        p.y_range.start = miny
        p.y_range.end   = maxy

search_button.on_click(run_search)

def on_text_input_change(attr, old, new):
    # Press Enter => run_search
    run_search()

text_input.on_change("value", on_text_input_change)
apply_radius_button.on_click(run_search)

def on_tile_select_change(attr, old, new):
    if new == "CartoDB Positron":
        provider = CARTODBPOSITRON
    else:
        provider = ESRI_IMAGERY

    for fig in [p_old, p_new, p_combined, p_blocks]:
        old_tile = tile_map.get(fig)
        if old_tile in fig.renderers:
            fig.renderers.remove(old_tile)
        new_tile = fig.add_tile(provider)
        tile_map[fig] = new_tile

tile_select.on_change("value", on_tile_select_change)

def run_extra_search():
    val = extra_taz_input.value.strip()
    if not val:
        extra_old_taz_source.data = {"xs": [], "ys": [], "id": []}
        extra_old_taz_text_source.data = {"cx": [], "cy": [], "id": []}
        return
    try:
        id_list = [int(x.strip()) for x in val.split(",") if x.strip()]
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
extra_taz_input.on_event("value_submit", lambda event: run_extra_search())

# -----------------------------------------------------------------------------
# 11) Dynamic TAZ Text Color Update (Top‐Right)
# -----------------------------------------------------------------------------
def update_new_taz_text_color(attr, old, new):
    selected = set(new_taz_source.selected.indices)
    colors = []
    for i in range(len(new_taz_text_source.data['id'])):
        if i in selected:
            colors.append("red")
        else:
            colors.append("rgba(0,0,0,0.3)")
    new_taz_text_source.data['color'] = colors

new_taz_source.selected.on_change("indices", update_new_taz_text_color)

# -----------------------------------------------------------------------------
# 12) Final Layout
# -----------------------------------------------------------------------------
top_maps = row(
    column(div_old_title, p_old, sizing_mode="stretch_both"),
    column(div_new_title, p_new, sizing_mode="stretch_both"),
    sizing_mode="stretch_both"
)
bot_maps = row(
    column(div_combined_title, p_combined, sizing_mode="stretch_both"),
    column(div_blocks_title,   p_blocks,   sizing_mode="stretch_both"),
    sizing_mode="stretch_both"
)

maps_col = column(top_maps, bot_maps, sizing_mode="stretch_both")

top_table = column(Div(text="<b>New TAZ Table</b>"), new_taz_data_table, sizing_mode="stretch_both")
bot_table = column(Div(text="<b>Blocks Table</b>"),  blocks_data_table,   sizing_mode="stretch_both")
tables_col = column(
    top_table,
    Spacer(height=20),
    bot_table,
    sizing_mode="stretch_both",
    width_policy="max",
    max_width=550
)

main_row = row(
    maps_col,
    tables_col,
    sizing_mode="stretch_both"
)

layout_final = column(
    row1_combined,
    row2,
    main_row,
    sizing_mode="stretch_both"
)

curdoc().add_root(layout_final)
curdoc().title = "VizTAZ - Extended with Updated Visuals"
