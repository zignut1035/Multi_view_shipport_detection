import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# 1. Load the data
file_path = "filtered_mystar_finlandia.json"
df = pd.read_json(file_path)

# Convert timestamp to a datetime object and sort it chronologically
df['timestamp'] = pd.to_datetime(df['timestamp'])
df = df.sort_values('timestamp')

# Set the dark theme
plt.style.use('dark_background')

# Separate the data into two dataframes
df_finlandia = df[df['name'] == 'FINLANDIA']
df_mystar = df[df['name'] == 'MYSTAR']


# ==========================================
# Plot 1: All Vessel Tracks (Overview)
# ==========================================
fig1, ax1 = plt.subplots(figsize=(8, 8))

# Plot both ships on the same map with dots for data points
ax1.plot(df_finlandia['lon'], df_finlandia['lat'], marker='o', linestyle='-', linewidth=1.5, color='#8dd3c7', label='FINLANDIA')
ax1.plot(df_mystar['lon'], df_mystar['lat'], marker='o', linestyle='-', linewidth=1.5, color='#fb8072', label='MYSTAR')

ax1.set_title('All Vessel Tracks (overview)')
ax1.set_xlabel('Longitude')
ax1.set_ylabel('Latitude')
ax1.ticklabel_format(useOffset=False, style='plain')
ax1.legend()

plt.tight_layout()
plt.show() # Close this window to see the next plot


# ==========================================
# Plot 2: Course/Heading over Time (BOTH)
# ==========================================
fig2, ax2 = plt.subplots(figsize=(10, 6))

# FINLANDIA Lines (Solid for Course, Dashed for Heading)
ax2.plot(df_finlandia['timestamp'], df_finlandia['cog'], label='FINLANDIA course', color='#8dd3c7', linewidth=2)
ax2.plot(df_finlandia['timestamp'], df_finlandia['heading'], label='FINLANDIA heading', color='#ffffb3', linestyle='--', linewidth=2)

# MYSTAR Lines (Solid for Course, Dashed for Heading)
ax2.plot(df_mystar['timestamp'], df_mystar['cog'], label='MYSTAR course', color='#fb8072', linewidth=2)
ax2.plot(df_mystar['timestamp'], df_mystar['heading'], label='MYSTAR heading', color='#bebada', linestyle='--', linewidth=2)

ax2.set_title('Course/Heading over Time — FINLANDIA & MYSTAR')
ax2.set_xlabel('Time (UTC)')
ax2.set_ylabel('Degrees')

# Format the x-axis to cleanly show the time
ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
fig2.autofmt_xdate(rotation=45) 

# Put the legend outside the plot so it doesn't cover up the lines
ax2.legend(loc='center left', bbox_to_anchor=(1, 0.5))

plt.tight_layout()
plt.show()