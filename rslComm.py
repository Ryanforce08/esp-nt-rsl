# tk_fms_status_serial.py
import sys
import tkinter as tk
from tkinter import ttk, messagebox
from ntcore import NetworkTableInstance
import serial
import serial.tools.list_ports
import time

SERVER_IP = "127.0.0.1"  # override via CLI arg
BAUD = 115200
DEFAULT_PORT = "/dev/ttyUSB0"  # override via UI

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
    def send_heartbeat(self):
        """Send a small 'PING' heartbeat message every second."""
        if not self.is_open():
            return
        try:
            payload = "Hallo\n".encode("ascii")
            self.ser.write(payload)
        except Exception:
            self.close()

def list_serial_ports():
    return [p.device for p in serial.tools.list_ports.comports()]

class FMSStatusApp:
    def __init__(self, root: tk.Tk, server_ip: str):
        self.root = root
        self.root.title("FMS / Robot Status → ESP32 LED")
        self.root.geometry("720x300")

        # Blinking setup
        self.blinking = False
        self.blink_state = False
        self.blink_rgb = None
        self.blink_bg = None
        self.blink_interval = 1000  # ms (1 sec)

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
        if DEFAULT_PORT in list_serial_ports():
            self.port_var.set(DEFAULT_PORT)
            self.toggle_connect()

        # --- NT4 setup ---
        self.ntinst = NetworkTableInstance.getDefault()
        self.ntinst.setServer(server_ip)
        self.ntinst.startClient4("TkFMSStatus")

        self.fms_table = self.ntinst.getTable("FMSInfo")
        self.fms_control = self.fms_table.getIntegerTopic("FMSControlData").subscribe(0)
        self.robot_table = self.ntinst.getTable("robot")
        self.voltage = self.robot_table.getDoubleTopic("voltage").subscribe(12.0)

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
    def start_blink(self, rgb_hex, interval=600):
        """Begin blinking a color without blocking poll()."""
        rgb = hex_to_rgb(rgb_hex)
        # If already blinking the same color, skip restarting
        if self.blinking and self.blink_rgb == rgb:
            return

        self.blinking = True
        self.blink_rgb = rgb
        self.blink_interval = interval
        self.blink_state = False
        self._blink_step()

    def stop_blink(self):
        """Stop blinking and restore normal color control."""
        if not self.blinking:
            return
        self.blinking = False
        self.blink_state = False
        if self.blink_rgb:
            # Restore final color to LED and UI
            hex_color = '#%02x%02x%02x' % self.blink_rgb
            self.serial.send_rgb_if_changed(self.blink_rgb)
            self.status_label.config(bg=hex_color)
        self.blink_rgb = None

    def _blink_step(self):
        """Toggle LED and background asynchronously."""
        if not self.blinking or not self.blink_rgb:
            return

        if self.blink_state:
            # Blink OFF
            print("Blink OFF")
            self.serial.send_rgb_if_changed(rgb=(255, 255, 0))
            self.status_label.config(bg="#dbdb00")
        else:
            # Blink ON
            rgb = self.blink_rgb
            self.serial.send_rgb_if_changed(rgb)
            self.status_label.config(bg='#%02x%02x%02x' % rgb)

        self.blink_state = not self.blink_state

        # Schedule next blink step — does NOT block poll()
        self.root.after(self.blink_interval, self._blink_step)



    # ----- Main poll loop -----
    def poll(self):
        code = self.fms_control.get()
        mode, enabled, attached = decode_fms(code)
        volt = self.voltage.get()

        if mode == "Unknown":
            label_text = "No Data"
            bg_hex = UI_COLORS["Unknown"]
        else:
            label_text = f"{'ENABLED' if enabled else 'DISABLED'}  ({mode.upper()})"
            bg_hex = UI_COLORS["Disabled"] if not enabled else UI_COLORS.get(mode, UI_COLORS["Unknown"])

        rgb = hex_to_rgb(bg_hex)

        # Handle voltage-based blinking
        if volt <= 10.0:
            label_text += " - LOW VOLTAGE!"
            self.start_blink(bg_hex, 600)
        else:
            self.stop_blink()
            # Only send normal color when not blinking
            self.serial.send_rgb_if_changed(rgb)
            self.status_label.config(bg=bg_hex)

        # Always update text info regardless of blinking
        self.status_label.config(text=label_text, fg="white")
        self.detail.config(
            text=f"FMS Attached: {'Yes' if attached else 'No'} | FMSControlData: {code}"
        )

        # Keep poll loop running continuously
        self.ntinst.flush()
        
        # Send heartbeat every ~1s
        now = time.time()
        if not hasattr(self, "_last_ping") or now - self._last_ping > 1.0:
            self.serial.send_heartbeat()
            self._last_ping = now

        self.root.after(100, self.poll)

def main():
    server = SERVER_IP
    if len(sys.argv) >= 2:
        server = sys.argv[1]
    root = tk.Tk()
    FMSStatusApp(root, server)
    root.mainloop()

if __name__ == "__main__":
    main()
