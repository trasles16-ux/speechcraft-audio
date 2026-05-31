"""
Network Monitor Support for SpeechCraft Studio
Allows voice actor's computer to serve as remote second monitor.

Server (NetworkMonitorServer):
  Runs on the director's machine (audio_editor.py side).
  Listens on port 8765, broadcasts JSON updates to all connected monitors.
  Handles multiple simultaneous client connections.

Client (NetworkMonitorClient):
  Standalone wx.Frame that connects to the director's machine.
  Displays current line, progress, and status.
  Integrates with braille_support for tactile output.
"""

import socket
import threading
import json
import time
import wx
import sys


class NetworkMonitorServer:
    """Server that broadcasts studio session data to remote monitors.
    
    Runs on the director's machine. The StudioRecorder calls
    broadcast_update() whenever state changes, and all connected
    monitor clients receive the update via TCP JSON stream.
    """
    
    def __init__(self, port=8765):
        self.port = port
        self.running = False
        self.clients = []  # [socket, ...]
        self.clients_lock = threading.Lock()  # Guards all client list operations
        self.server_socket = None
        self.current_data = {
            'status': 'Ready',
            'current_line': None,
            'progress': {
                'current_line': 0,
                'total_lines': 0,
                'progress_percent': 0
            },
            'transcription': ''
        }
    
    def start_server(self):
        """Start the TCP server and return the LAN IP address for clients."""
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # Bind to all interfaces so voice actor can connect from any machine on LAN
            self.server_socket.bind(('0.0.0.0', self.port))
            self.server_socket.listen(5)
            self.server_socket.settimeout(1.0)  # Poll every 1s for clean shutdown
            self.running = True
            
            local_ip = self._get_lan_ip()
            print(f"Network monitor server started on {local_ip}:{self.port}")
            
            threading.Thread(target=self._accept_connections, daemon=True).start()
            return local_ip
            
        except OSError as e:
            print(f"Failed to start network server: {e}")
            return None
    
    def _get_lan_ip(self):
        """Get the LAN IP address of this machine.
        
        Tries multiple methods to handle different network configurations.
        """
        # Method 1: connect to a dummy address and read the local socket name
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))  # Doesn't actually send packets
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            pass
        
        # Method 2: gethostbyname (usually works on Windows)
        try:
            hostname = socket.gethostname()
            ip = socket.gethostbyname(hostname)
            # Reject loopback — loopback is useless for LAN connections
            if not ip.startswith(('127.', '0.')):
                return ip
        except Exception:
            pass
        
        # Method 3: scan common LAN ranges
        for hint in ('192.168.1.', '192.168.0.', '10.0.'):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(0.1)
                s.connect((f'{hint}1', 53))
                ip = s.getsockname()[0]
                s.close()
                if not ip.startswith('127.'):
                    return ip
            except Exception:
                pass
        
        return '127.0.0.1'  # Fallback — won't work for LAN but tells user something is wrong
    
    def _accept_connections(self):
        """Accept incoming client connections."""
        while self.running:
            try:
                client_socket, addr = self.server_socket.accept()
                # Enable keepalive so dead connections are detected quickly
                client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                print(f"Voice actor monitor connected from {addr}")
                
                with self.clients_lock:
                    self.clients.append(client_socket)
                
                threading.Thread(
                    target=self._handle_client,
                    args=(client_socket, addr),
                    daemon=True
                ).start()
                
            except socket.timeout:
                continue  # Polling loop — check self.running and continue
            except OSError:
                if self.running:
                    pass  # Socket was closed during accept — expected on shutdown
                break
    
    def _handle_client(self, client_socket, addr):
        """Handle individual client connection — send state, then wait for disconnect."""
        try:
            # Send current state immediately on connect
            self._send_to_client(client_socket, self.current_data)
            
            # Wait for disconnect (client will close the socket)
            while self.running:
                time.sleep(1)
                
        except OSError:
            pass  # Client disconnected or network error
        finally:
            with self.clients_lock:
                if client_socket in self.clients:
                    self.clients.remove(client_socket)
            try:
                client_socket.close()
            except OSError:
                pass
    
    def _send_to_client(self, client_socket, data):
        """Send JSON data to a specific client. Removes client on error."""
        try:
            message = json.dumps(data) + '\n'
            client_socket.sendall(message.encode('utf-8'))
        except OSError:
            # Remove dead client — caller may have already removed it, that's fine
            with self.clients_lock:
                if client_socket in self.clients:
                    self.clients.remove(client_socket)
            try:
                client_socket.close()
            except OSError:
                pass
    
    def broadcast_update(self, data):
        """Broadcast update to all connected clients.
        
        Called by StudioRecorder._broadcast() whenever state changes.
        Thread-safe — holds lock while iterating over the client list.
        """
        self.current_data.update(data)
        
        with self.clients_lock:
            clients_snapshot = list(self.clients)
        
        for client in clients_snapshot:
            self._send_to_client(client, self.current_data)
    
    def stop_server(self):
        """Stop the server and disconnect all clients."""
        self.running = False
        
        with self.clients_lock:
            for client in self.clients:
                try:
                    client.close()
                except OSError:
                    pass
            self.clients = []
        
        if self.server_socket:
            try:
                self.server_socket.close()
            except OSError:
                pass


class NetworkMonitorClient(wx.Frame):
    """Client window that connects to the director's machine.
    
    Provides the voice actor with a live view of the current script line,
    session progress, and status updates. Integrates with braille_support
    to display the current line on a braille display when connected.
    """
    
    def __init__(self, server_ip, port=8765):
        super().__init__(None, title="Voice Actor Monitor (Network)", size=(600, 500))
        
        self.server_ip = server_ip
        self.port = port
        self.socket = None
        self.connected = False
        
        self.init_ui()
        self.connect_to_server()
    
    def init_ui(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)
        
        # Connection status
        self.connection_status = wx.StaticText(panel, label="Connecting...")
        status_font = self.connection_status.GetFont()
        status_font.SetPointSize(10)
        self.connection_status.SetFont(status_font)
        vbox.Add(self.connection_status, 0, wx.ALL | wx.ALIGN_CENTER, 5)
        
        # Large title
        title = wx.StaticText(panel, label="Voice Actor Monitor")
        title_font = title.GetFont()
        title_font.SetPointSize(18)
        title_font.SetWeight(wx.FONTWEIGHT_BOLD)
        title.SetFont(title_font)
        vbox.Add(title, 0, wx.ALL | wx.ALIGN_CENTER, 15)
        
        # Current line display
        line_box = wx.StaticBox(panel, label="Current Line to Record")
        line_sizer = wx.StaticBoxSizer(line_box, wx.VERTICAL)
        
        self.current_line_text = wx.TextCtrl(
            panel,
            style=wx.TE_MULTILINE | wx.TE_READONLY,
            size=(-1, 200)
        )
        line_font = self.current_line_text.GetFont()
        line_font.SetPointSize(14)
        line_font.SetWeight(wx.FONTWEIGHT_BOLD)
        self.current_line_text.SetFont(line_font)
        line_sizer.Add(self.current_line_text, 1, wx.EXPAND | wx.ALL, 5)
        
        vbox.Add(line_sizer, 1, wx.EXPAND | wx.ALL, 10)
        
        # Progress display
        progress_box = wx.StaticBox(panel, label="Session Progress")
        progress_sizer = wx.StaticBoxSizer(progress_box, wx.VERTICAL)
        
        self.progress_gauge = wx.Gauge(panel, range=100, size=(-1, 40))
        progress_sizer.Add(self.progress_gauge, 0, wx.EXPAND | wx.ALL, 5)
        
        self.progress_text = wx.StaticText(panel, label="Waiting for session...")
        progress_font = self.progress_text.GetFont()
        progress_font.SetPointSize(12)
        self.progress_text.SetFont(progress_font)
        progress_sizer.Add(self.progress_text, 0, wx.ALL | wx.ALIGN_CENTER, 5)
        
        vbox.Add(progress_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        # Status display
        self.status_text = wx.StaticText(panel, label="Ready")
        status_font = self.status_text.GetFont()
        status_font.SetPointSize(14)
        status_font.SetWeight(wx.FONTWEIGHT_BOLD)
        self.status_text.SetFont(status_font)
        vbox.Add(self.status_text, 0, wx.ALL | wx.ALIGN_CENTER, 15)
        
        panel.SetSizer(vbox)
    
    def connect_to_server(self):
        """Connect to the director's computer in a background thread."""
        def connect_worker():
            try:
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                self.socket.settimeout(10.0)  # Initial connection timeout
                self.socket.connect((self.server_ip, self.port))
                self.socket.settimeout(None)  # No timeout on recv after connect
                self.connected = True
                
                wx.CallAfter(self.connection_status.SetLabel, f"Connected to {self.server_ip}")
                self._receive_data()
                
            except OSError as e:
                wx.CallAfter(
                    self.connection_status.SetLabel,
                    f"Connection failed: {e}"
                )
        
        threading.Thread(target=connect_worker, daemon=True).start()
    
    def _receive_data(self):
        """Receive JSON updates from the server and update the UI."""
        buffer = ""
        while self.connected:
            try:
                data = self.socket.recv(4096).decode('utf-8')
                if not data:
                    break  # Server closed connection
                
                buffer += data
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    if line.strip():
                        try:
                            update = json.loads(line)
                            wx.CallAfter(self._update_ui, update)
                        except json.JSONDecodeError:
                            pass
                            
            except OSError:
                break  # Network error or server closed connection
            
        self.connected = False
        wx.CallAfter(self.connection_status.SetLabel, "Disconnected")
    
    def _update_ui(self, data):
        """Update UI with received server data."""
        if 'status' in data:
            self.status_text.SetLabel(data['status'])
        
        if 'progress' in data:
            progress = data['progress']
            self.progress_gauge.SetValue(int(progress.get('progress_percent', 0)))
            self.progress_text.SetLabel(
                f"Line {progress.get('current_line', 0)} of {progress.get('total_lines', 0)}"
            )
        
        if 'current_line' in data and data['current_line']:
            line = data['current_line']
            line_text = f"Line {line.get('line_number', '?')}:\n\n"
            line_text += line.get('description', 'No description')
            self.current_line_text.SetValue(line_text)
            
            # Send to braille display if available
            try:
                import braille_support
                braille_support.send_line_to_braille(
                    line.get('line_number', 0),
                    line.get('description', '')
                )
            except (ImportError, AttributeError):
                pass  # Braille not available — non-critical


def start_network_monitor_client():
    """Start the network monitor client application.
    
    Called as a standalone script (python network_monitor.py) or launched
    from audio_editor.py when the voice actor is on a separate machine.
    """
    app = wx.App()
    
    dlg = wx.TextEntryDialog(
        None,
        "Enter director's computer IP address:",
        "Connect to Studio"
    )
    if dlg.ShowModal() == wx.ID_OK:
        server_ip = dlg.GetValue().strip()
        if server_ip:
            frame = NetworkMonitorClient(server_ip)
            frame.Show()
            app.MainLoop()
    
    dlg.Destroy()


if __name__ == "__main__":
    start_network_monitor_client()