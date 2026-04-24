import gmplot

# Define the bounding box edges (Rotterdam: Erasmusbrug & Cruise Terminal)
MINLAT = 51.9040
MAXLAT = 51.9180
MINLON = 4.4820
MAXLON = 4.4960

# Calculate the center of the map to initialize the plotter
center_lat = (MINLAT + MAXLAT) / 2
center_lon = (MINLON + MAXLON) / 2

# Create the map plotter centered on Rotterdam (Zoom level 14)
gmap = gmplot.GoogleMapPlotter(center_lat, center_lon, 14)

# Sample AIS data (Adjusted to actually be in Rotterdam!)
# This plots a path moving down the river, passing the Cruise Terminal and Erasmusbrug
lats = [51.9050, 51.9090, 51.9130] 
longs = [4.4910, 4.4870, 4.4810]

# Plot the ship's trajectory
gmap.plot(lats, longs, 'cornflowerblue', edge_width=3)

# Plot a red rectangle to visualize your exact bounding box limits
box_lats = [MINLAT, MAXLAT, MAXLAT, MINLAT, MINLAT]
box_lons = [MINLON, MINLON, MAXLON, MAXLON, MINLON]
gmap.plot(box_lats, box_lons, 'red', edge_width=2)

# Draw to HTML
gmap.draw("rotterdam_ship_trajectory.html")