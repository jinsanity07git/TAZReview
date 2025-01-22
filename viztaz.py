import geopandas
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import contextily as ctx
from IPython.core.display import  HTML
from IPython.display import display
class Review:
    def __init__(self, oldtaz):
        self.oldtaz = oldtaz

        url = r".\shapefiles\taz_new_Jan14_1.shp"
        self.ggdf = geopandas.read_file(url)

        url = r".\shapefiles\blocks20a.shp"
        self.bldf = geopandas.read_file(url)

        url = r".\shapefiles\CTPS_TDM23_TAZ_2017g_v202303.shp"
        self.ogdf = geopandas.read_file(url)

    def before_after(self,       
                    show_layers = {
                        'old_taz': True,
                        'blocks': True,
                        'new_taz': True,
                        'labels': True,
                        'basemap': True
                    }, 
                     styles = {
                        'old_taz': {
                        'face_color': "#DFBC1E",
                        'edge_color': 'blue',
                        'alpha': 0.2,
                        'line_width': 1,
                        'line_style': '-'
                        },
                        'blocks': {
                        'edge_color': 'black',
                        'line_width': 1,
                        'line_style': '-.'
                        },
                        'new_taz': {
                        'edge_color': 'red',
                        'line_width': 2,
                        'line_style': (0, (2, 10))
                        }
                    },
                    legend = False):
        """

        """
        oldtarget = self.ogdf.query(f"taz_id in {self.oldtaz}")
        
        # Create a buffer around the oldtarget area
        buffer_distance = .05 * 1609.34  # 5 miles in meters
        oldtarget_buffer = oldtarget.buffer(buffer_distance)
        
        # Filter the blocks,old taz that intersect with the buffer
        bldf_filtered = self.bldf[self.bldf.intersects(oldtarget_buffer.unary_union)]
        ogdf_filtered = self.ggdf[self.ggdf.intersects(oldtarget_buffer.unary_union)]

        # Create a figure and axes
        fig, ax = plt.subplots(figsize=(16,9), facecolor='none')
        # First, ensure the GeoDataFrames are in Web Mercator projection (EPSG:3857)
        oldtarget = oldtarget.to_crs(epsg=3857)
        bldf_filtered = bldf_filtered.to_crs(epsg=3857)
        ogdf_filtered = ogdf_filtered.to_crs(epsg=3857)

        # Plot layers
        if show_layers['old_taz']:
            oldtarget.plot(color=styles['old_taz']['face_color'], 
                 alpha=styles['old_taz']['alpha'], ax=ax)
            oldtarget.boundary.plot(ax=ax, 
                      color=styles['old_taz']['edge_color'],
                      alpha=styles['old_taz']['alpha']*2,
                      linewidth=styles['old_taz']['line_width'],
                      linestyle=styles['old_taz']['line_style'])

        if show_layers['blocks']:
            bldf_filtered.boundary.plot(ax=ax, 
                          color=styles['blocks']['edge_color'],
                          linewidth=styles['blocks']['line_width'],
                          linestyle=styles['blocks']['line_style'])

        if show_layers['new_taz']:
            ogdf_filtered.boundary.plot(ax=ax, 
                          color=styles['new_taz']['edge_color'],
                          linewidth=styles['new_taz']['line_width'],
                          linestyle=styles['new_taz']['line_style'])

        if show_layers['labels']:
            for idx, row in oldtarget.iterrows():
                minx, miny, maxx, maxy = row.geometry.bounds
                x, y = (minx+maxx)/2, (miny+maxy)/2
                ax.text(x, y, str(row['taz_id']), fontsize=12, 
                    ha='center', va='center', 
                    color=styles['old_taz']['edge_color'])

        if show_layers['basemap']:
            ctx.add_basemap(ax, source=ctx.providers.CartoDB.Positron, zoom='auto')

        # Create legend matching the actual styles
        proxy_artists = [
            Patch(facecolor=styles['old_taz']['face_color'], 
             edgecolor=styles['old_taz']['edge_color'],
             alpha=styles['old_taz']['alpha'], 
             label="Old TAZ #"),
            Patch(facecolor='none',
             edgecolor=styles['new_taz']['edge_color'], 
             linestyle=styles['new_taz']['line_style'],
             linewidth=styles['new_taz']['line_width'], 
             label="New TAZ"),
            Patch(facecolor='none',
             edgecolor=styles['blocks']['edge_color'],
             linestyle=styles['blocks']['line_style'],
             linewidth=styles['blocks']['line_width'], 
             label="block"),
        ]
        # Remove x-axis and y-axis
        ax.axis('off')
        if legend:
            
            ax.legend(handles=proxy_artists, loc='center left', bbox_to_anchor=(1, 0.5))
            # Adjust layout to prevent legend from being cut off
            plt.tight_layout()
            # Show the plot
            plt.show()

            # Calculate the center latitude and longitude of the oldtarget area
            oldtarget_projected = oldtarget.to_crs(epsg=3857)
            oldtarget_centroid = oldtarget_projected.geometry.centroid.to_crs(epsg=4326)
            center_lat = oldtarget_centroid.y.mean()
            center_lon = oldtarget_centroid.x.mean()
            gmapweb = f"https://www.google.com/maps/@{center_lat},{center_lon},15z/data=!3m1!1e3"
            htmlstr = f"""<a href="{gmapweb}" 
                                target="_blank"'>jump to google map</a>"""
            display(HTML(htmlstr))
            # print(gmapweb)
            # return center_lat, center_lon


if __name__ == "__main__":

    oldtaz = [5]
    review = Review(oldtaz)
    review.before_after(oldtaz)