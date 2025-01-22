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

    def before_after(self,oldtaz):
        """
        oldtaz,newtaz = [5],[6,7]
        oldtaz -- old taz
        newtaz -- new taz
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
        opacity = 0.2
        # Plot the geometries with some transparency (alpha) so we can see the basemap
        oldtarget.plot(color="#DFBC1E", alpha=opacity, ax=ax)
        oldtarget.boundary.plot(ax=ax, alpha=opacity*2, linewidth=1, color='blue')
        bldf_filtered.boundary.plot(ax=ax, linewidth=1, linestyle='-.', color='black')
        ogdf_filtered.boundary.plot(ax=ax, linewidth=2, linestyle=(0, (2, 10)), color='red')
        # Add text annotations for each polygon in oldtarget
        for idx, row in oldtarget.iterrows():
            # Get the left top (minimum x, maximum y) of the polygon
            minx, miny, maxx, maxy = row.geometry.bounds
            x = (minx+maxx)/2
            y = (miny+maxy)/2
            # Add text annotation
            ax.text(x, y, str(row['taz_id']), fontsize=12, ha='center', va='center', 
                    color='blue')

        # Add the basemap
        ctx.add_basemap(ax, 
                        source=ctx.providers.CartoDB.Positron,
                        zoom='auto')
        # Create legend
        proxy_artists = [
            Patch(facecolor="#DFBC1E", alpha=opacity, label="Old TAZ #"),
            Patch(edgecolor="red", facecolor='none', linewidth=2, linestyle=(0, (2, 10)), label="New TAZ"),
            Patch(edgecolor="black", facecolor='none', linestyle='--', linewidth=1, label="block"),
        ]
        # Remove x-axis and y-axis
        ax.axis('off')
        ax.legend(handles=proxy_artists, loc='center left', bbox_to_anchor=(1, 0.5))
        # Adjust layout to prevent legend from being cut off
        plt.tight_layout()
        # Show the plot
        plt.show()

        # Calculate the center latitude and longitude of the oldtarget area
        oldtarget_centroid = oldtarget.to_crs(epsg=4326).geometry.centroid
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