import os
import sys
import glob
import geopandas as gpd

# Set working directory to the location of this script.
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Use command-line arguments if provided, otherwise prompt the user.
if len(sys.argv) >= 3:
    folder_path = sys.argv[1]
    output_geojson = sys.argv[2]
else:
    folder_path = input("Please enter the name of the folder that contains the shapefile pending for conversion: ").strip()
    output_geojson = input("Please enter the desired name for the output GeoJSON file (include the '.geojson' extension): ").strip()

# Search for shapefiles (*.shp) in the provided folder.
shapefile_list = glob.glob(os.path.join(folder_path, "*.shp"))

if shapefile_list:
    # Take the first found shapefile.
    shapefile_path = shapefile_list[0]
    print(f"Found shapefile: {shapefile_path}")

    # Read the shapefile and convert its coordinate system to EPSG:4326 (WGS84).
    gdf = gpd.read_file(shapefile_path)
    gdf = gdf.to_crs(epsg=4326)

    # Write the converted data as GeoJSON.
    gdf.to_file(output_geojson, driver="GeoJSON")
    print(f"Conversion successful! The output has been saved as: {output_geojson}")
else:
    print("No shapefile was found in the specified folder. Please verify the folder name and try again.")
