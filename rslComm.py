import sys
import tkinter as tk
from tkinter import ttk, messagebox
from ntcore import NetworkTableInstance
import time
from serialHelper import SerialLink

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
    "Unknown": "#000000",
    "Disabled": "#00ff00",
    "Auto": "#0000ff",
    "Test": "#800080",
    "Teleop": "#ff0000",
}

def hex_to_rgb(hex_str):
    hex_str = hex_str.lstrip("#")
    return tuple(int(hex_str[i:i+2], 16) for i in (0, 2, 4))

def decode_fms(code: int):
    if code in FMS_CODES:
        return FMS_CODES[code]
    return ("Unknown", False, False)


# -------- FMSStatusApp Class --------
class FMSStatusApp:
    def __init__(self, root: tk.Tk, server_ip: str):
        self.root = root
        self.root.title("FMS / Robot Status → ESP32 LED")
        self.root.geometry("720x350")

        self.title_font = ("Segoe UI", 14, "bold")
        self.big_font = ("Segoe UI", 28, "bold")
        self.small_font = ("Segoe UI", 11)
        self.brightness = 0.5

        self.blinking = False
        self.blink_state = False
        self.blink_rgb = None
        self.blink_hex = None
        self.blink_interval = 1.0  # seconds
        self.last_time = 0.0

        # --- Header ---
        header = tk.Label(root, text="NetworkTables: FMSInfo", font=self.title_font)
        header.pack(pady=(10, 4))

        # --- Status Label ---
        self.status_label = tk.Label(root, text="Connecting…", font=self.big_font, width=28, height=2)
        self.status_label.pack(pady=6)

        # --- Details ---
        self.detail = tk.Label(root, text="—", font=self.small_font)
        self.detail.pack()

        # --- Server Label ---
        self.server_lbl = tk.Label(root, text=f"NT Server: {server_ip}", font=self.small_font, fg="#666")
        self.server_lbl.pack(pady=(6, 0))

        # --- Serial Frame ---
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

        # --- Brightness ---
        self.bright_frame = ttk.LabelFrame(root, text=f"LED Brightness: {self.brightness:.2f}")
        self.bright_frame.pack(fill="x", padx=10, pady=6)

        def on_brightness_change(val):
            self.brightness = float(val) / 100.0
            self.bright_frame.config(text=f"LED Brightness: {self.brightness:.2f}")
            if hasattr(self, "serial"):
                self.serial.set_brightness(self.brightness)

        self.brightness_slider = ttk.Scale(
            self.bright_frame, from_=0, to=100, orient="horizontal",
            command=on_brightness_change
        )
        self.brightness_slider.set(self.brightness * 100)
        self.brightness_slider.pack(fill="x", padx=10, pady=8)

        # --- Initialize SerialLink ---
        self.serial = SerialLink(
            baud=BAUD,
            default_port=DEFAULT_PORT,
            heartbeat_interval=0.5,
            heartbeat_message="Hallo\n",
            auto_reconnect=True,
            tk_root=self.root,
            brightness=self.brightness
        )

        self.serial.on_connect = self._on_serial_connect
        self.serial.on_disconnect = self._on_serial_disconnect
        self.serial.on_reconnect = self._on_serial_reconnect

        self.refresh_ports()
        if self.port_var.get() not in self.serial.list_ports() and DEFAULT_PORT in self.serial.list_ports():
            self.port_var.set(DEFAULT_PORT)
        elif self.port_var.get() not in self.serial.list_ports():
            self.port_var.set("")

        # --- NetworkTables Setup ---
        self.init_nt(server_ip)

        # Start poll loop
        self.root.after(100, self.poll)

        # Clean shutdown
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # --- Serial callbacks ---
    def _on_serial_connect(self):
        self.connect_btn.config(text="Disconnect")
        self.conn_label.config(text=f"Connected: {self.serial.ser.port}", foreground="#2E7D32")
        self.serial.start_heartbeat()
        self.serial.send_rgb(self.rgb)  # reset LEDs on connect
        self.serial.send_rgb(self.rgb)  # reset LEDs on connect
        self.serial.send_rgb(self.rgb)  # reset LEDs on connect

    def _on_serial_disconnect(self):
        self.connect_btn.config(text="Connect")
        self.conn_label.config(text="Disconnected", foreground="#B00020")
        self.serial.stop_heartbeat()

    def _on_serial_reconnect(self):
        self.conn_label.config(text=f"Reconnected: {self.serial.ser.port}", foreground="#2E7D32")
        self.serial.start_heartbeat()
        time.sleep(0.5)
        self.serial.send_rgb(self.rgb)  # reset LEDs on connect
        self.serial.send_rgb(self.rgb)  # reset LEDs on connect
        self.serial.send_rgb(self.rgb)  # reset LEDs on connect

    # --- Refresh ports ---
    def refresh_ports(self):
        ports = self.serial.list_ports()
        self.port_menu["values"] = ports
        if ports and (self.port_var.get() not in ports):
            self.port_var.set(ports[0])
        elif not ports:
            self.port_var.set("")

    # --- Connect/Disconnect ---
    def toggle_connect(self):
        if self.serial.is_open():
            self.serial.close()
        else:
            port = self.port_var.get().strip()
            if not port:
                messagebox.showwarning("Serial", "Select a serial port first.")
                return
            self.serial.open(port)

    # --- NetworkTables Setup ---
    def init_nt(self, server_ip):
        self.ntinst = NetworkTableInstance.getDefault()
        self.ntinst.setServer(server_ip)
        self.ntinst.startClient4("TkFMSStatus")
        self.fms_table = self.ntinst.getTable("FMSInfo")
        self.fms_control = self.fms_table.getIntegerTopic("FMSControlData").subscribe(0)
        self.robot_table = self.ntinst.getTable("robot")
        self.voltage = self.robot_table.getDoubleTopic("voltage").subscribe(12.0)

    # --- Poll Loop ---
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
        self.rgb = rgb

        # Voltage blinking
        if volt <= 10.0:
            label_text += " - LOW VOLTAGE!"
            if not self.blinking:
                self.start_blink(rgb)
        elif self.blinking and volt > 10.0:
            self.stop_blink()
        elif not self.blinking:
            self.serial.send_rgb_if_changed(rgb)
        if self.blinking:
            bg_hex = self.blink_hex

        self.status_label.config(text=label_text, fg="white",background=bg_hex)
        self.detail.config(text=f"FMS Attached: {'Yes' if attached else 'No'} | FMSControlData: {code}")

        self.ntinst.flush()
        self.root.after(100, self.poll)

    # --- Blinking Logic ---
    def start_blink(self, rgb):
        if self.blinking and self.blink_rgb == rgb:
            return
        self.blinking = True
        self.blink_rgb = rgb
        self.blink_state = False
        self._blink_step()

    def stop_blink(self):
        if not self.blinking:
            return
        self.blinking = False
        self.blink_state = False
        if self.blink_rgb:
            self.serial.send_rgb_if_changed(self.blink_rgb)
        self.blink_rgb = None

    def _blink_step(self):
        if not self.blinking or not self.blink_rgb:
            return
        now = time.time()
        if now - self.last_time < self.blink_interval:
            self.root.after(50, self._blink_step)
            return
        self.last_time = now
        if self.blink_state:
            self.serial.send_rgb_if_changed((255, 255, 0))
            self.blink_hex = "#ffff00"
        else:
            self.serial.send_rgb_if_changed(self.blink_rgb)
            
        self.blink_state = not self.blink_state
        self.root.after(50, self._blink_step)

    # --- Clean Shutdown ---
    def on_close(self):
        try:
            self.serial.stop_heartbeat()
        except Exception:
            pass
        try:
            self.serial.close()
        except Exception:
            pass
        try:
            self.ntinst.stopClient()
        except Exception:
            pass

        self.root.destroy()


# --- Main Entry ---
def main():
    server = SERVER_IP
    if len(sys.argv) >= 2:
        server = sys.argv[1]
    root = tk.Tk()
    FMSStatusApp(root, server)
    root.mainloop()


if __name__ == "__main__":
    main()
