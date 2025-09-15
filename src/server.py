#!/usr/bin/env python3
from flask import Flask, jsonify, send_file, request
import psycopg2
from psycopg2.extras import RealDictCursor
import json
import re
from datetime import datetime, timedelta

app = Flask(__name__)

DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'hmdm',
    'user': 'hmdm', 
    'password': 'topsecret'
}

@app.route('/')
def index():
    return send_file('index-history.html')

@app.route('/api/locations')
def get_locations():
    """Get current device locations"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("""
            SELECT id, number, description, imei, info 
            FROM devices 
            WHERE info IS NOT NULL 
            ORDER BY number
        """)
        devices = cur.fetchall()
        
        result = []
        
        for device in devices:
            try:
                info_json = json.loads(device['info'])
                
                if 'location' in info_json and info_json['location']:
                    loc = info_json['location']
                    lat = loc.get('lat')
                    lon = loc.get('lon')
                    timestamp = loc.get('ts')
                    
                    if lat and lon and lat != 0 and lon != 0:
                        if timestamp:
                            location_time = datetime.fromtimestamp(timestamp / 1000)
                        else:
                            location_time = datetime.now()
                            
                        result.append({
                            'id': device['id'],
                            'number': device['number'],
                            'description': device['description'] or 'Unknown Device',
                            'imei': device['imei'],
                            'lat': float(lat),
                            'lon': float(lon),
                            'time': location_time.isoformat(),
                            'status': 'active'
                        })
                        
            except (json.JSONDecodeError, ValueError, TypeError) as e:
                continue
        
        cur.close()
        conn.close()
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def parse_gps_from_message(message):
    """Extract lat/lon from GPS log messages"""
    pattern = r'lat=(-?\d+\.?\d*),?\s*lon=(-?\d+\.?\d*)'
    match = re.search(pattern, message)
    if match:
        return float(match.group(1)), float(match.group(2))
    return None, None

@app.route('/api/device/<device_number>/history')
def get_device_history(device_number):
    """Get real location history for a specific device from GPS logs"""
    days = int(request.args.get('days', 7))
    
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Get device info
        cur.execute("""
            SELECT id, number, description 
            FROM devices 
            WHERE number = %s
        """, (device_number,))
        
        device = cur.fetchone()
        if not device:
            return jsonify({"error": "Device not found"}), 404
        
        # Get GPS location updates from device logs
        since_time = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)
        
        cur.execute("""
            SELECT createtime, message 
            FROM plugin_devicelog_log 
            WHERE deviceid = %s 
              AND message LIKE %s
              AND createtime > %s
            ORDER BY createtime ASC
        """, (device['id'], '%GPS location update%', since_time))
        
        log_entries = cur.fetchall()
        history_points = []
        
        # Process GPS log entries
        for entry in log_entries:
            lat, lon = parse_gps_from_message(entry['message'])
            if lat and lon:
                point_time = datetime.fromtimestamp(entry['createtime'] / 1000)
                history_points.append({
                    'lat': lat,
                    'lon': lon,
                    'time': point_time.isoformat(),
                    'type': 'logged'
                })
        
        # If no logged GPS data, try location_history table as fallback
        if not history_points:
            cur.execute("""
                SELECT lat, lon, recorded_at, source
                FROM location_history
                WHERE device_id = %s
                  AND recorded_at > NOW() - INTERVAL %s
                ORDER BY recorded_at ASC
            """, (device['id'], f"{days} days"))
            
            history_entries = cur.fetchall()
            for entry in history_entries:
                history_points.append({
                    'lat': float(entry['lat']),
                    'lon': float(entry['lon']),
                    'time': entry['recorded_at'].isoformat(),
                    'type': 'backup'
                })
        
        # If still no history, add current location from device info
        if not history_points:
            cur.execute("SELECT info FROM devices WHERE id = %s", (device['id'],))
            device_info = cur.fetchone()
            if device_info and device_info['info']:
                try:
                    info_json = json.loads(device_info['info'])
                    if 'location' in info_json:
                        loc = info_json['location']
                        lat, lon = loc.get('lat'), loc.get('lon')
                        if lat and lon:
                            timestamp = loc.get('ts')
                            if timestamp:
                                point_time = datetime.fromtimestamp(timestamp / 1000)
                            else:
                                point_time = datetime.now()
                            
                            history_points.append({
                                'lat': float(lat),
                                'lon': float(lon),
                                'time': point_time.isoformat(),
                                'type': 'current'
                            })
                except:
                    pass
        
        cur.close()
        conn.close()
        
        return jsonify({
            'device': {
                'number': device['number'],
                'description': device['description']
            },
            'history': history_points,
            'total_points': len(history_points)
        })
        
    except Exception as e:
        print(f"Error getting device history: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/devices')
def get_devices():
    """Get list of all devices, showing GPS history count"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Get all devices with GPS log counts
        cur.execute("""
            SELECT d.number, d.description,
                   COALESCE(gps_counts.gps_updates, 0) as gps_updates
            FROM devices d 
            LEFT JOIN (
                SELECT deviceid, COUNT(*) as gps_updates
                FROM plugin_devicelog_log 
                WHERE message LIKE %s
                GROUP BY deviceid
            ) gps_counts ON gps_counts.deviceid = d.id
            WHERE d.info IS NOT NULL
            ORDER BY d.description, d.number
        """, ('%GPS location update%',))
        devices = cur.fetchall()
        
        cur.close()
        conn.close()
        
        result = []
        for d in devices:
            name_display = d['description'] or d['number']
            if d['gps_updates'] > 0:
                name_display += f" ({d['gps_updates']} GPS updates)"
            else:
                name_display += " (No GPS history)"
            
            result.append({
                'number': d['number'],
                'name': name_display,
                'gps_count': d['gps_updates']
            })
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/debug/gps-logs')
def debug_gps_logs():
    """Debug endpoint to see GPS log structure"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("""
            SELECT d.number, d.description, 
                   to_timestamp(l.createtime/1000) as time,
                   l.message
            FROM plugin_devicelog_log l
            JOIN devices d ON d.id = l.deviceid  
            WHERE l.message LIKE %s
            ORDER BY l.createtime DESC 
            LIMIT 10
        """, ('%GPS location update%',))
        
        logs = cur.fetchall()
        cur.close()
        conn.close()
        
        return jsonify([dict(log) for log in logs])
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    print("Starting Headwind MDM Maps with REAL Location History")
    print("Visit: http://localhost:5003")
    print("Debug GPS logs: http://localhost:5003/api/debug/gps-logs")
    app.run(debug=True, host='0.0.0.0', port=5003)
