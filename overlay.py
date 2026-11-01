import os
import sys
import webview
from typing import Dict, Any

from live_tracker import LiveTracker

class OverlayAPI:
    """
    API expuesta a JavaScript en el Mini-Overlay Flotante.
    """
    def __init__(self):
        self.tracker = LiveTracker()
        self.window = None

    def get_overlay_state(self) -> Dict[str, Any]:
        """Devuelve el estado en tiempo real (CS, KDA, Matchup, Build)."""
        return self.tracker.get_overlay_state()

    def toggle_compact(self, is_compact: bool):
        """Alterna entre el tamaño de tarjeta completo y la barra compacta."""
        if self.window:
            if is_compact:
                self.window.resize(330, 48)
            else:
                self.window.resize(330, 420)

    def close_overlay(self):
        """Cierra el overlay."""
        if self.window:
            self.window.destroy()
        sys.exit(0)

def main():
    api = OverlayAPI()
    gui_dir = os.path.join(os.path.dirname(__file__), "gui")
    overlay_html = os.path.join(gui_dir, "overlay.html")

    window = webview.create_window(
        title="LoL Companion Mini-Overlay",
        url=overlay_html,
        js_api=api,
        width=330,
        height=420,
        x=40,
        y=40,
        frameless=True,
        on_top=True,
        easy_drag=True,
        resizable=False,
        background_color="#000000"
    )
    api.window = window
    webview.start(debug=False)

if __name__ == "__main__":
    main()
