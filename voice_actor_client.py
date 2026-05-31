#!/usr/bin/env python3
"""
Voice Actor Monitor - Standalone Client
Connects to SpeechCraft Studio director's computer
Requires only Python 3 (no additional installations)
"""

import socket
import json
import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import sys

class VoiceActorMonitor:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Voice Actor Monitor")
        self.root.geometry("600x500")
        
        self.socket = None
        self.connected = False
        
        self.setup_ui()
        
    def setup_ui(self):
        # Connection frame
        conn_frame = tk.Frame(self.root)
        conn_frame.pack(fill=tk.X, padx=10, pady=5)
        
        tk.Label(conn_frame, text="Director's IP:").pack(side=tk.LEFT)
        self.ip_entry = tk.Entry(conn_frame, width=15)
        self.ip_entry.pack(side=tk.LEFT, padx=5)
        self.ip_entry.insert(0, "192.168.1.")
        
        self.connect_btn = tk.Button(conn_frame, text="Connect", command=self.connect)
        self.connect_btn.pack(side=tk.LEFT, padx=5)
        
        self.status_label = tk.Label(conn_frame, text="Not connected", fg="red")
        self.status_label.pack(side=tk.LEFT, padx=10)
        
        # Main content
        main_frame = tk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Current line
        tk.Label(main_frame, text="Current Line:", font=("Arial", 12, "bold")).pack(anchor=tk.W)
        
        self.line_text = tk.Text(main_frame, height=8, font=("Arial", 14, "bold"), 
                                wrap=tk.WORD, state=tk.DISABLED)
        self.line_text.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # Progress
        progress_frame = tk.Frame(main_frame)
        progress_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(progress_frame, text="Progress:", font=("Arial", 10)).pack(anchor=tk.W)
        self.progress_bar = ttk.Progressbar(progress_frame, length=400, mode='determinate')
        self.progress_bar.pack(fill=tk.X, pady=2)
        
        self.progress_label = tk.Label(progress_frame, text="Waiting...", font=("Arial", 10))
        self.progress_label.pack(anchor=tk.W)
        
        # Status
        self.session_status = tk.Label(main_frame, text="Ready", 
                                     font=("Arial", 16, "bold"), fg="blue")
        self.session_status.pack(pady=10)
        
    def connect(self):
        ip = self.ip_entry.get().strip()
        if not ip:
            messagebox.showerror("Error", "Please enter director's IP address")
            return
            
        def connect_worker():
            try:
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                # Fail fast if director's machine is unreachable (avoids indefinite hang)
                self.socket.settimeout(10.0)
                self.socket.connect((ip, 8765))
                # Once connected, remove timeout so recv() blocks indefinitely
                # (expected behaviour for an open socket)
                self.socket.settimeout(None)
                self.connected = True

                self.root.after(0, lambda: self.status_label.config(text="Connected", fg="green"))
                self.root.after(0, lambda: self.connect_btn.config(state=tk.DISABLED))

                self.receive_data()

            except socket.timeout:
                self.root.after(0, lambda: messagebox.showerror(
                    "Connection Timeout",
                    f"Could not reach director's computer at {ip}.\n\n"
                    "Check that SpeechCraft Studio is running on the director's machine."
                ))
            except Exception as e:
                self.root.after(0, lambda err=str(e): messagebox.showerror("Connection Error", err))
                
        threading.Thread(target=connect_worker, daemon=True).start()
        
    def receive_data(self):
        buffer = ""
        while self.connected:
            try:
                data = self.socket.recv(1024).decode('utf-8')
                if not data:
                    break
                    
                buffer += data
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    if line.strip():
                        try:
                            update = json.loads(line)
                            self.root.after(0, lambda u=update: self.update_display(u))
                        except json.JSONDecodeError:
                            pass
                            
            except Exception as e:
                print(f"Receive error: {e}")
                break

        self.connected = False
        # Guard UI updates in case the Tk window was closed while the thread was running
        try:
            if self.root.winfo_exists():
                self.root.after(0, lambda: self.status_label.config(text="Disconnected", fg="red"))
                self.root.after(0, lambda: self.connect_btn.config(state=tk.NORMAL))
        except Exception:
            pass
        
    def update_display(self, data):
        # Update status
        if 'status' in data:
            self.session_status.config(text=data['status'])
            
        # Update progress
        if 'progress' in data:
            progress = data['progress']
            percent = progress.get('progress_percent', 0)
            self.progress_bar['value'] = percent
            
            current = progress.get('current_line', 0)
            total = progress.get('total_lines', 0)
            self.progress_label.config(text=f"Line {current} of {total} ({percent:.0f}%)")
            
        # Update current line
        if 'current_line' in data and data['current_line']:
            line = data['current_line']
            line_num = line.get('line_number', '?')
            description = line.get('description', 'No description')
            
            display_text = f"Line {line_num}:\n\n{description}"
            
            self.line_text.config(state=tk.NORMAL)
            self.line_text.delete(1.0, tk.END)
            self.line_text.insert(1.0, display_text)
            self.line_text.config(state=tk.DISABLED)
            
    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    print("Voice Actor Monitor - Standalone Client")
    print("Connecting to SpeechCraft Studio...")
    
    app = VoiceActorMonitor()
    app.run()