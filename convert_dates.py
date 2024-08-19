import sqlite3
from datetime import datetime

# Step 1: Connect to the SQLite3 database
connection = sqlite3.connect('/mnt/wsl_projects/gen_playlist2/instance/kTunes.sqlite')

# Step 2: Create a cursor object
cursor = connection.cursor()

# Step 3: Select rows from the tracks table
cursor.execute("SELECT id, last_play_dt, date_added, ktunes_last_play_dt FROM tracks")
rows = cursor.fetchall()

# Function to convert date strings to the desired format
def convert_date(date_value):
    if date_value is None or date_value == 'UNKNOWN' or date_value == 0:
        return '1900-01-01 12:00:00'
    if isinstance(date_value, int):
        try:
            return datetime.fromtimestamp(date_value).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return '1900-01-01 12:00:00'
    try:
        return datetime.strptime(date_value, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return '1900-01-01 12:00:00'  # Return the default date if it cannot be parsed

# Step 4: Loop through the rows and convert the date fields
for row in rows:
    id, last_play_dt, date_added, ktunes_last_play_dt = row
    
    # Convert date fields to the desired format
    last_play_dt = convert_date(last_play_dt)
    date_added = convert_date(date_added)
    ktunes_last_play_dt = convert_date(ktunes_last_play_dt)
    
    # Step 5: Update the rows with the new date format
    cursor.execute("""
        UPDATE tracks
        SET last_play_dt = ?, date_added = ?, ktunes_last_play_dt = ?
        WHERE id = ?
    """, (last_play_dt, date_added, ktunes_last_play_dt, id))

# Step 6: Commit the changes and close the connection
connection.commit()
cursor.close()
connection.close()

print("Date conversion completed successfully.")