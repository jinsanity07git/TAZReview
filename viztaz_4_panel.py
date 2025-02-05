import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import contextily as ctx

# Load shapefiles
url_old_taz = r"./shapefiles/CTPS_TDM23_TAZ_2017g_v202303.shp"
url_new_taz = r"./shapefiles/taz_new_Jan14_1.shp"
url_blocks = r"./shapefiles/blocks20a.shp"

gdf_old_taz = gpd.read_file(url_old_taz)
gdf_new_taz = gpd.read_file(url_new_taz)
gdf_blocks = gpd.read_file(url_blocks)

def sync_axes(event):
    """Synchronize zooming and panning across all subplots."""
    if event.inaxes:
        xlim, ylim = event.inaxes.get_xlim(), event.inaxes.get_ylim()
        for ax in axes.flat:
            ax.set_xlim(xlim)
            ax.set_ylim(ylim)
        plt.draw()

def compare_taz_blocks(old_taz_list):
    """
    Generate a four-panel plot showing old TAZ, new TAZ, blocks, and combined layers.
    """
    # Filter old TAZ areas
    old_taz = gdf_old_taz[gdf_old_taz['taz_id'].isin(old_taz_list)]
    buffer_distance = 0.05 * 1609.34  # 5 miles in meters
    buffer_area = old_taz.buffer(buffer_distance).unary_union
    
    # Filter relevant blocks and new TAZs
    blocks_filtered = gdf_blocks[gdf_blocks.intersects(buffer_area)]
    new_taz_filtered = gdf_new_taz[gdf_new_taz.intersects(buffer_area)]
    
    # Convert to Web Mercator for visualization
    old_taz = old_taz.to_crs(epsg=3857)
    blocks_filtered = blocks_filtered.to_crs(epsg=3857)
    new_taz_filtered = new_taz_filtered.to_crs(epsg=3857)
    
    global fig, axes
    fig, axes = plt.subplots(2, 2, figsize=(16, 12), facecolor='none')
    fig.canvas.mpl_connect('scroll_event', sync_axes)
    fig.canvas.mpl_connect('button_release_event', sync_axes)
    fig.canvas.mpl_connect('motion_notify_event', sync_axes)
    
    # Top-left: Old TAZ
    old_taz.plot(ax=axes[0, 0], color='none', edgecolor='green')
    axes[0, 0].set_title("Old TAZ", fontsize=14, fontweight='bold')
    axes[0, 0].axis('off')
    ctx.add_basemap(axes[0, 0], source=ctx.providers.CartoDB.Positron, zoom='auto')
    
    # Top-right: New TAZ
    new_taz_filtered.plot(ax=axes[0, 1], color='none', edgecolor='red')
    axes[0, 1].set_title("New TAZ", fontsize=14, fontweight='bold')
    axes[0, 1].axis('off')
    ctx.add_basemap(axes[0, 1], source=ctx.providers.CartoDB.Positron, zoom='auto')
    
    # Bottom-left: Blocks layer
    blocks_filtered.plot(ax=axes[1, 0], color='#F9E79F', alpha=0.5, edgecolor='black', linewidth=1.5, linestyle='-')
    axes[1, 0].set_title("Blocks Layer", fontsize=14, fontweight='bold')
    axes[1, 0].axis('off')
    ctx.add_basemap(axes[1, 0], source=ctx.providers.CartoDB.Positron, zoom='auto')
    
    # Bottom-right: Combined layers
    old_taz.plot(ax=axes[1, 1], color='none', edgecolor='green')
    new_taz_filtered.plot(ax=axes[1, 1], color='none', edgecolor='red')
    blocks_filtered.plot(ax=axes[1, 1], color='#DFBC1E', alpha=0.3, edgecolor='black', linestyle=':')
    axes[1, 1].set_title("Combined Layers", fontsize=14, fontweight='bold')
    axes[1, 1].axis('off')
    ctx.add_basemap(axes[1, 1], source=ctx.providers.CartoDB.Positron, zoom='auto')
    
    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    compare_taz_blocks([5])
