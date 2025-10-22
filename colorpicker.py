# hsv_color_box_sender_display.py
import tkinter as tk
import colorsys
import serial
import threading
import time
from serialHelper import SerialLink

# ---------- Configuration ----------
PORT = "/dev/ttyUSB2"  # Change to your serial port
BAUD = 115200
HEARTBEAT_INTERVAL = 1.0  # seconds
SEND_INTERVAL = 0.05  # seconds
SIZE = 256  # color square size (pixels)

# ---------- Serial Setup ----------
try:
    ser = SerialLink(baud=BAUD, default_port=PORT, heartbeat_interval=HEARTBEAT_INTERVAL)
    ser.open()
    print(f"Connected to {PORT} at {BAUD}")
except Exception as e:
    print("Serial not available:", e)
    ser = None


class ColorPickerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ESP32 HSV Color Picker")

        # Color preview
        self.preview = tk.Label(root, text="     ", bg="#ff0000", width=20, height=2)
        self.preview.pack(pady=(6, 4))

        # Create a color gradient area
        self.img = tk.PhotoImage(width=SIZE, height=SIZE)
        self.canvas = tk.Canvas(root, width=SIZE, height=SIZE)
        self.canvas.pack()
        self.canvas.create_image((0, 0), image=self.img, anchor="nw")

        self.cursor = self.canvas.create_oval(125, 125, 135, 135, outline="black", width=2)
        self.current_rgb = (255, 0, 0)

        # Generate color map
        self.generate_hsv_square()

        # Info labels
        self.rgb_label = tk.Label(root, text="RGB: 255, 0, 0", font=("Segoe UI", 11))
        self.rgb_label.pack(pady=(8, 2))
        self.hex_label = tk.Label(root, text="HEX: #FF0000", font=("Segoe UI", 11))
        self.hex_label.pack()

        # Bind drag events
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<Button-1>", self.on_drag)

        # Threads
        self.running = True
        threading.Thread(target=self.sender_thread, daemon=True).start()
        ser.send_heartbeat()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def generate_hsv_square(self):
        """Generate HSV color gradient and draw it."""
        for x in range(SIZE):
            hue = x / SIZE
            for y in range(SIZE):
                val = 1.0 - (y / SIZE)
                sat = 1.0
                r, g, b = [int(c * 255) for c in colorsys.hsv_to_rgb(hue, sat, val)]
                self.img.put(f"#{r:02x}{g:02x}{b:02x}", (x, y))

    def on_drag(self, event):
        x = max(0, min(SIZE - 1, event.x))
        y = max(0, min(SIZE - 1, event.y))
        self.canvas.coords(self.cursor, x - 5, y - 5, x + 5, y + 5)
        self.current_rgb = self.get_color_at(x, y)
        self.update_display()

    def get_color_at(self, x, y):
        hue = x / SIZE
        val = 1.0 - (y / SIZE)
        sat = 1.0
        r, g, b = [int(c * 255) for c in colorsys.hsv_to_rgb(hue, sat, val)]
        return (r, g, b)

    def update_display(self):
        r, g, b = self.current_rgb
        hex_val = f"#{r:02X}{g:02X}{b:02X}"
        self.preview.config(bg=hex_val)
        self.rgb_label.config(text=f"RGB: {r}, {g}, {b}")
        self.hex_label.config(text=f"HEX: {hex_val}")

    def sender_thread(self):
        """Continuously send the current color to ESP32."""
        while self.running:
            r, g, b = self.current_rgb
            ser.send_rgb_if_changed((255,255,255))
            time.sleep(SEND_INTERVAL)


    def on_close(self):
        self.running = False
        if ser:
            ser.stop_heartbeat()
            ser.close()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = ColorPickerApp(root)
    root.mainloop()
