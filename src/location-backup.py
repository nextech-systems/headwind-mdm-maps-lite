#!/usr/bin/env python3
import psycopg2
import json
import time
from datetime import datetime

DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'hmdm',
    'user': 'hmdm', 
    'password': 'topsecret'
}

def save_current_locations():
    """Save current device locations to history table"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        
        # Get all devices with location data
        cur.execute("""
            SELECT id, number, info 
            FROM devices 
            WHERE info IS NOT NULL
        """)
        
        devices = cur.fetchall()
        locations_saved = 0
        
        for device in devices:
            try:
                info_json = json.loads(device[2])  # info column
                
                if 'location' in info_json and info_json['location']:
                    loc = info_json['location']
                    lat = loc.get('lat')
                    lon = loc.get('lon')
                    
                    if lat and lon and lat != 0 and lon != 0:
                        # Check if this location already exists recently (avoid duplicates)
                        cur.execute("""
                            SELECT COUNT(*) FROM location_history 
                            WHERE device_id = %s 
                              AND lat = %s 
                              AND lon = %s 
                              AND recorded_at > NOW() - INTERVAL '10 minutes'
                        """, (device[0], float(lat), float(lon)))
                        
                        if cur.fetchone()[0] == 0:
                            # Save to location_history table
                            cur.execute("""
                                INSERT INTO location_history (device_id, lat, lon, source)
                                VALUES (%s, %s, %s, 'auto-save')
                            """, (device[0], float(lat), float(lon)))
                            locations_saved += 1
                        
            except (json.JSONDecodeError, ValueError, TypeError) as e:
                print(f"Error processing device {device[1]}: {e}")
                continue
        
        conn.commit()
        cur.close()
        conn.close()
        
        print(f"{datetime.now()}: Saved {locations_saved} new device locations")
        
    except Exception as e:
        print(f"Error saving locations: {e}")

if __name__ == '__main__':
    print("Starting location auto-save service...")
    while True:
        save_current_locations()
        time.sleep(300)  # Save every 5 minutes
