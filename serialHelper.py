import serial
import serial.tools.list_ports
import threading
import time

class SerialLink:
    """
    Serial helper for ESP32 or similar microcontrollers.
    Handles connection, reconnection, RGB updates, automatic heartbeat,
    Tkinter-safe callbacks, and automatic brightness scaling.
    """
    def __init__(self, baud=115200, default_port=None,
                 heartbeat_interval=1.0, heartbeat_message="Hallo/n",
                 auto_reconnect=True, tk_root=None, brightness=1.0):
        self.baud = baud
        self.default_port = default_port
        self.heartbeat_interval = heartbeat_interval
        self.heartbeat_message = heartbeat_message
        self.auto_reconnect = auto_reconnect
        self.tk_root = tk_root
        self.brightness = max(0.0, min(1.0, brightness))

        self.ser = None
        self.lock = threading.Lock()
        self.last_rgb = None
        self._hb_thread = None
        self._hb_stop = threading.Event()

        # Tkinter callbacks
        self.on_connect = None
        self.on_disconnect = None
        self.on_reconnect = None

    # -------- Connection Management --------
    def list_ports(self):
        return [p.device for p in serial.tools.list_ports.comports()]

    def open(self, port=None):
        self.close()
        port = port or self.default_port
        if not port:
            ports = self.list_ports()
            if not ports:
                return False
            port = ports[0]
        try:
            self.ser = serial.Serial(port=port, baudrate=self.baud, timeout=0)
            self.last_rgb = None
            self.start_heartbeat()
            self._tk_callback(self.on_connect)
            return True
        except Exception as e:
            self.ser = None
            print(f"[SerialLink] Failed to open {port}: {e}")
            return False

    def close(self):
        self.stop_heartbeat()
        with self.lock:
            if self.ser and self.ser.is_open:
                try:
                    self.ser.close()
                except Exception:
                    pass
            if self.ser:
                self._tk_callback(self.on_disconnect)
            self.ser = None
            self.last_rgb = None

    def is_open(self):
        return self.ser is not None and self.ser.is_open

    # -------- Brightness --------
    def set_brightness(self, value):
        """Set brightness (0.0–1.0) and update last sent RGB if any."""
        self.brightness = max(0.0, min(1.0, value))
        if self.last_rgb:
            scaled = tuple(int(c * self.brightness) for c in self.last_rgb)
            self.send_rgb_if_changed(scaled)

    # -------- Message Sending --------
    def send_message(self, message, only_if_changed=False):
        if not self.is_open():
            if self.auto_reconnect and self.try_reconnect():
                self._tk_callback(self.on_reconnect)
            if not self.is_open():
                return False

        if only_if_changed and message == getattr(self, "_last_sent", None):
            return False

        with self.lock:
            try:
                if not message.endswith("\n"):
                    message += "\n"
                self.ser.write(message.encode("ascii"))
                self._last_sent = message
                return True
            except Exception as e:
                print(f"[SerialLink] Write failed: {e}")
                self.close()
                return False

    # -------- RGB Control --------
    def send_rgb_if_changed(self, rgb):
        """Send RGB color scaled by brightness, only if changed."""
        if not self.is_open() and self.auto_reconnect:
            self.try_reconnect()
        if not self.is_open():
            return False

        scaled_rgb = tuple(max(0, min(255, int(c * self.brightness))) for c in rgb)
        if self.last_rgb == scaled_rgb:
            return False

        ok = self.send_message(f"LED {scaled_rgb[0]} {scaled_rgb[1]} {scaled_rgb[2]}")
        if ok:
            self.last_rgb = scaled_rgb
        return ok

    def send_heartbeat(self):
        return self.send_message(self.heartbeat_message, only_if_changed=False)

    # -------- Heartbeat Thread --------
    def start_heartbeat(self):
        if self._hb_thread and self._hb_thread.is_alive():
            return
        self._hb_stop.clear()
        self._hb_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._hb_thread.start()

    def stop_heartbeat(self):
        self._hb_stop.set()

    def _heartbeat_loop(self):
        while not self._hb_stop.is_set():
            if self.is_open():
                self.send_heartbeat()
            elif self.auto_reconnect:
                if self.try_reconnect():
                    self._tk_callback(self.on_reconnect)
            time.sleep(self.heartbeat_interval)

    # -------- Auto-Reconnect --------
    def try_reconnect(self):
        ports = self.list_ports()
        if not ports:
            return False
        target = self.default_port or ports[0]
        try:
            self.ser = serial.Serial(port=target, baudrate=self.baud, timeout=0)
            self.last_rgb = None
            self._tk_callback(self.on_reconnect)
            print(f"[SerialLink] Reconnected to {target}")
            return True
        except Exception:
            return False

    # -------- Tkinter-safe callback helper --------
    def _tk_callback(self, callback):
        if self.tk_root and callback:
            self.tk_root.after(0, callback)