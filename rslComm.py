# tk_fms_status_serial.py
import sys
import tkinter as tk
from tkinter import ttk, messagebox
from ntcore import NetworkTableInstance
import serial
import serial.tools.list_ports

SERVER_IP = "127.0.0.1"  # override via CLI arg
BAUD = 115200

# Map of FMSControlData codes → (mode, enabled?, fms_attached?)
FMS_CODES = {
    # Not attached
    32: ("Disabled", False, False),
    33: ("Teleop",   True,  False),
    35: ("Auto",     True,  False),
    37: ("Test",     True,  False),
    # Attached
    48: ("Disabled", False, True),
    49: ("Teleop",   True,  True),
    51: ("Auto",     True,  True),
    53: ("Test",     True,  True),
}

# UI color palette (hex) matching the big status label background
UI_COLORS = {
    "Unknown": "#808080",
    "Disabled": "#00ff00",
    "Auto": "#0000ff",
    "Test": "#f9a825",
    "Teleop": "#ff0000",
}

def hex_to_rgb(hex_str):
    hex_str = hex_str.lstrip("#")
    return tuple(int(hex_str[i:i+2], 16) for i in (0, 2, 4))

def decode_fms(code: int):
    if code in FMS_CODES:
        return FMS_CODES[code]
    return ("Unknown", False, False)

class SerialLink:
    def __init__(self):
        self.ser = None
        self.last_rgb = None  # (r,g,b) last transmitted

    def open(self, port, baud=BAUD):
        self.close()
        self.ser = serial.Serial(port=port, baudrate=baud, timeout=0)
        self.last_rgb = None

    def close(self):
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None
        self.last_rgb = None

    def is_open(self):
        return self.ser is not None and self.ser.is_open

    def send_rgb_if_changed(self, rgb):
        """Send only when the RGB changed to reduce spam."""
        if not self.is_open():
            return
        if self.last_rgb == rgb:
            return
        r, g, b = rgb
        try:
            payload = f"LED {r} {g} {b}\n".encode("ascii")
            self.ser.write(payload)
            self.last_rgb = rgb
        except Exception:
            # If write fails, drop the link silently; UI will show disconnected on next check
            try:
                self.close()
            except Exception:
                pass

def list_serial_ports():
    return [p.device for p in serial.tools.list_ports.comports()]

class FMSStatusApp:
    def __init__(self, root, server_ip):
        self.root = root
        self.root.title("FMS / Robot Status → ESP32 LED")
        self.root.geometry("620x300")

        # Fonts
        self.title_font = ("Segoe UI", 14, "bold")
        self.big_font = ("Segoe UI", 28, "bold")
        self.small_font = ("Segoe UI", 11)

        # --- Header ---
        header = tk.Label(root, text="NetworkTables: FMSInfo", font=self.title_font)
        header.pack(pady=(10, 4))

        # --- Status label ---
        self.status_label = tk.Label(root, text="Connecting…", font=self.big_font, width=28, height=2)
        self.status_label.pack(pady=6)

        # --- Details ---
        self.detail = tk.Label(root, text="—", font=self.small_font)
        self.detail.pack()

        # --- NT server display ---
        self.server_lbl = tk.Label(root, text=f"NT Server: {server_ip}", font=self.small_font, fg="#666")
        self.server_lbl.pack(pady=(6, 0))

        # --- Serial controls ---
        ser_frame = ttk.LabelFrame(root, text="ESP32 Serial Link (WS2812 on IO16)")
        ser_frame.pack(fill="x", padx=10, pady=10)

        self.port_var = tk.StringVar()
        self.port_menu = ttk.Combobox(ser_frame, textvariable=self.port_var, state="readonly", width=24)
        self.port_menu.grid(row=0, column=0, padx=8, pady=6, sticky="w")

        self.refresh_btn = ttk.Button(ser_frame, text="Refresh", command=self.refresh_ports)
        self.refresh_btn.grid(row=0, column=1, padx=6, pady=6)

        self.connect_btn = ttk.Button(ser_frame, text="Connect", command=self.toggle_connect)
        self.connect_btn.grid(row=0, column=2, padx=6, pady=6)

        self.conn_label = ttk.Label(ser_frame, text="Disconnected", foreground="#B00020")
        self.conn_label.grid(row=0, column=3, padx=8, pady=6, sticky="w")

        ser_frame.grid_columnconfigure(4, weight=1)

        # Init serial helper
        self.serial = SerialLink()
        self.refresh_ports()

        # --- NT4 setup ---
        self.ntinst = NetworkTableInstance.getDefault()
        self.ntinst.setServer(server_ip)
        self.ntinst.startClient4("TkFMSStatus")

        self.fms_table = self.ntinst.getTable("FMSInfo")
        self.fms_control = self.fms_table.getIntegerTopic("FMSControlData").subscribe(0)

        # Periodic loop
        self.poll()

        # Clean shutdown
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ----- Serial UI helpers -----
    def refresh_ports(self):
        ports = list_serial_ports()
        self.port_menu["values"] = ports
        if ports and (self.port_var.get() not in ports):
            self.port_var.set(ports[0])
        elif not ports:
            self.port_var.set("")

    def toggle_connect(self):
        if self.serial.is_open():
            self.serial.close()
            self.connect_btn.config(text="Connect")
            self.conn_label.config(text="Disconnected", foreground="#B00020")
            return

        port = self.port_var.get().strip()
        if not port:
            messagebox.showwarning("Serial", "Select a serial port first.")
            return
        try:
            self.serial.open(port, BAUD)
            self.connect_btn.config(text="Disconnect")
            self.conn_label.config(text=f"Connected: {port}", foreground="#2E7D32")
        except Exception as e:
            messagebox.showerror("Serial", f"Failed to open {port}\n{e}")
            self.serial.close()
            self.connect_btn.config(text="Connect")
            self.conn_label.config(text="Disconnected", foreground="#B00020")

    def on_close(self):
        try:
            self.serial.close()
        except Exception:
            pass
        try:
            self.ntinst.stopClient()
        except Exception:
            pass
        self.root.destroy()

    # ----- Main poll loop -----
    def poll(self):
        code = self.fms_control.get()
        mode, enabled, attached = decode_fms(code)

        if mode == "Unknown":
            label_text = "No Data"
            bg_hex = UI_COLORS["Unknown"]
        else:
            label_text = f"{'ENABLED' if enabled else 'DISABLED'}  ({mode.upper()})"
            bg_hex = UI_COLORS["Disabled"] if not enabled else UI_COLORS.get(mode, UI_COLORS["Unknown"])

        # Update UI
        self.status_label.config(text=label_text, bg=bg_hex, fg="white")
        self.detail.config(
            text=f"FMS Attached: {'Yes' if attached else 'No'}    |    FMSControlData: {code}"
        )

        # Send RGB to ESP32 if changed
        rgb = hex_to_rgb(bg_hex)
        self.serial.send_rgb_if_changed(rgb)

        # Flush NT and schedule again
        self.ntinst.flush()
        self.root.after(100, self.poll)  # ~10 Hz

def main():
    server = SERVER_IP
    if len(sys.argv) >= 2:
        server = sys.argv[1]
    root = tk.Tk()
    FMSStatusApp(root, server)
    root.mainloop()

if __name__ == "__main__":
    main()
