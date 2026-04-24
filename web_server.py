"""
Simple Web Server for MicroPython Sensor System Monitoring

Provides a lightweight HTTP server with a web UI for monitoring:
- System resources (CPU, RAM)
- Sensor statistics
- Algorithm performance
- Real-time status

Designed for Raspberry Pi Pico W with minimal resource usage.
"""

import socket
import json
import time
import gc
import asyncio
from lib.utils.system_monitor import get_monitor


class WebServer:
    """
    Lightweight HTTP server for system monitoring.
    
    Serves a simple HTML dashboard and JSON API endpoints.
    """
    
    def __init__(self, port=80):
        """
        Initialize the web server.
        
        Args:
            port: HTTP port to listen on (default: 80)
        """
        self.port = port
        try:
            self.monitor = get_monitor()
            print(f"[WebServer] System monitor initialized")
        except Exception as e:
            print(f"[WebServer] Error initializing monitor: {e}")
            self.monitor = None
        self.socket = None
        print(f"[WebServer] Initialized on port {port}")
    
    async def start(self):
        """Start the web server (async, non-blocking with cooperative yielding)."""
        try:
            # Create socket
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind(('0.0.0.0', self.port))
            self.socket.listen(5)
            # Set to non-blocking mode immediately
            self.socket.setblocking(False)
            
            print(f"[WebServer] Listening on port {self.port}")
            print(f"[WebServer] Access the dashboard at http://<pico-ip>:{self.port}/")
            
            request_count = 0
            
            while True:
                try:
                    # Try to accept connection (non-blocking)
                    try:
                        conn, addr = self.socket.accept()
                        request_count += 1
                        print(f"[WebServer] Connection #{request_count} from {addr}")
                        
                        # Handle request with timeout protection
                        await self._handle_request_async(conn, addr)
                        conn.close()
                        
                        # Yield after handling request
                        await asyncio.sleep(0)
                        
                    except OSError as e:
                        # No connection available (EAGAIN/EWOULDBLOCK)
                        # Yield to other tasks with short sleep
                        await asyncio.sleep(0.05)
                        
                except Exception as e:
                    print(f"[WebServer] Error in accept loop: {e}")
                    await asyncio.sleep(0.1)
                finally:
                    # Periodic garbage collection (every 10 requests)
                    if request_count % 10 == 0:
                        gc.collect()
                    
        except Exception as e:
            print(f"[WebServer] Fatal error: {e}")
            raise
        finally:
            if self.socket:
                self.socket.close()
    
    async def _handle_request_async(self, conn, addr):
        """Handle an HTTP request asynchronously with timeout protection."""
        try:
            # Set connection to non-blocking with timeout
            conn.settimeout(2.0)  # 2 second timeout for read
            
            # Read request with bounded size
            request_data = b''
            max_request_size = 2048  # Limit request size
            
            try:
                # Read in small chunks to avoid blocking
                while len(request_data) < max_request_size:
                    chunk = conn.recv(512)
                    if not chunk:
                        break
                    request_data += chunk
                    # Check if we have complete headers
                    if b'\r\n\r\n' in request_data:
                        break
                    # Yield periodically
                    await asyncio.sleep(0)
                
                request = request_data.decode('utf-8')
            except socket.timeout:
                print(f"[WebServer] Timeout reading from {addr}")
                return
            except Exception as e:
                print(f"[WebServer] Error reading request: {e}")
                return
            
            # Parse and route request
            self._route_request(conn, request)
            
        except Exception as e:
            print(f"[WebServer] Error in _handle_request_async: {e}")
            try:
                self._serve_500(conn)
            except:
                pass
    
    def _route_request(self, conn, request):
        """Parse and route HTTP request to appropriate handler."""
        try:
            # Parse request line
            lines = request.split('\r\n')
            if len(lines) == 0:
                return
            
            request_line = lines[0]
            parts = request_line.split(' ')
            if len(parts) < 2:
                return
            
            method = parts[0]
            path = parts[1]
            
            print(f"[WebServer] {method} {path}")
            
            # Route request
            if path == '/' or path == '/index.html':
                self._serve_dashboard(conn)
            elif path == '/api/summary':
                self._serve_api_summary(conn)
            elif path == '/api/memory':
                self._serve_api_memory(conn)
            elif path == '/api/sensors':
                self._serve_api_sensors(conn)
            elif path == '/api/algorithms':
                self._serve_api_algorithms(conn)
            else:
                self._serve_404(conn)
                
        except Exception as e:
            print(f"[WebServer] Error in _route_request: {e}")
            self._serve_500(conn)
    
    
    def _send_response(self, conn, status, content_type, body):
        """Send an HTTP response."""
        try:
            # Encode body first to get correct byte length
            body_bytes = body.encode('utf-8')
            
            response = f"HTTP/1.1 {status}\r\n"
            response += f"Content-Type: {content_type}\r\n"
            response += f"Content-Length: {len(body_bytes)}\r\n"
            response += "Connection: close\r\n"
            response += "\r\n"
            
            conn.send(response.encode('utf-8'))
            conn.send(body_bytes)
        except Exception as e:
            print(f"[WebServer] Error sending response: {e}")
    
    def _serve_dashboard(self, conn):
        """Serve the main dashboard HTML."""
        print("[WebServer] GET /")
        html = """<!DOCTYPE html>
<html>
<head>
<title>Pico Monitor</title>
<meta charset="UTF-8">
</head>
<body>
<h1>Pico System Monitor</h1>
<p>Last Update: <span id="time">-</span></p>
<h2>Memory</h2>
<p>Free: <strong id="memFree">-</strong></p>
<p>Used: <strong id="memUsed">-</strong></p>
<p>Usage: <strong id="memPercent">-</strong></p>
<h2>System</h2>
<p>Uptime: <strong id="uptime">-</strong></p>
<h2>Sensors</h2>
<div id="sensors">-</div>
<h2>Algorithms</h2>
<div id="algorithms">-</div>
<h2>LoRa Messages</h2>
<div id="lora">-</div>
<script>
function update(){
fetch('/api/summary')
.then(r=>r.json())
.then(data=>{
document.getElementById('time').textContent=new Date().toLocaleTimeString();
document.getElementById('memFree').textContent=Math.round(data.memory.free/1024)+' KB';
document.getElementById('memUsed').textContent=Math.round(data.memory.used/1024)+' KB';
document.getElementById('memPercent').textContent=data.memory.used_percent.toFixed(1)+'%';
document.getElementById('uptime').textContent=data.uptime.formatted;
let s='';
for(const[id,stats]of Object.entries(data.sensors.stats)){
s+='<p>'+id+': '+stats.total_readings+' readings</p>';
}
document.getElementById('sensors').innerHTML=s||'None';
let a='';
for(const[id,stats]of Object.entries(data.algorithms.stats)){
a+='<p>'+id+': '+stats.total_executions+' exec, '+stats.total_triggers+' triggers</p>';
}
document.getElementById('algorithms').innerHTML=a||'None';
let l='';
if(data.lora_messages&&data.lora_messages.length>0){
for(const msg of data.lora_messages.slice(0,10)){
const timeStr = msg.time_formatted || new Date(msg.time*1000).toLocaleTimeString();
l+='<p><span style="color:#666;margin-right:8px">['+timeStr+']</span><strong>'+msg.algo+'</strong> @ '+msg.sensor+': <span style="color:#0066cc">'+msg.value+'</span></p>';
}
}
document.getElementById('lora').innerHTML=l||'No messages';
})
.catch(err=>{
console.error('Error:',err);
document.getElementById('time').textContent='ERROR: '+err.message;
});
}
update();
setInterval(update,1000);
</script>
</body>
</html>"""
        self._send_response(conn, "200 OK", "text/html", html)
    
    def _serve_api_summary(self, conn):
        """Serve complete system summary as JSON."""
        try:
            print("[WebServer] GET /api/summary")
            summary = self.monitor.get_summary()
            print(f"[WebServer] Sensors count: {summary['sensors']['count']}")
            print(f"[WebServer] Algorithms count: {summary['algorithms']['count']}")
            print(f"[WebServer] LoRa messages count: {len(summary.get('lora_messages', []))}")
            json_data = json.dumps(summary)
            self._send_response(conn, "200 OK", "application/json", json_data)
        except Exception as e:
            print(f"[WebServer] Error in /api/summary: {e}")
            import sys
            sys.print_exception(e)
            self._serve_500(conn)
    
    def _serve_api_memory(self, conn):
        """Serve memory info as JSON."""
        try:
            memory = self.monitor.get_memory_info()
            json_data = json.dumps(memory)
            self._send_response(conn, "200 OK", "application/json", json_data)
        except Exception as e:
            print(f"[WebServer] Error in _serve_api_memory: {e}")
            self._serve_500(conn)
    
    def _serve_api_sensors(self, conn):
        """Serve sensor stats as JSON."""
        try:
            sensors = self.monitor.get_sensor_stats()
            json_data = json.dumps(sensors)
            self._send_response(conn, "200 OK", "application/json", json_data)
        except Exception as e:
            print(f"[WebServer] Error in _serve_api_sensors: {e}")
            self._serve_500(conn)
    
    def _serve_api_algorithms(self, conn):
        """Serve algorithm stats as JSON."""
        try:
            algorithms = self.monitor.get_algorithm_stats()
            json_data = json.dumps(algorithms)
            self._send_response(conn, "200 OK", "application/json", json_data)
        except Exception as e:
            print(f"[WebServer] Error in _serve_api_algorithms: {e}")
            self._serve_500(conn)
    
    def _serve_404(self, conn):
        """Serve 404 Not Found."""
        html = "<html><body><h1>404 Not Found</h1></body></html>"
        self._send_response(conn, "404 Not Found", "text/html", html)
    
    def _serve_500(self, conn):
        """Serve 500 Internal Server Error."""
        html = "<html><body><h1>500 Internal Server Error</h1></body></html>"
        self._send_response(conn, "500 Internal Server Error", "text/html", html)


# Example usage (run in separate task):
# import asyncio
# from web_server import WebServer
# 
# async def web_server_task():
#     server = WebServer(port=80)
#     server.start()  # Blocking call
# 
# # Add to main.py asyncio.gather():
# # asyncio.gather(..., web_server_task())


# Made with Bob