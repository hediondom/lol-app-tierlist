import os
import sys
import json
import time
import ctypes
import threading
from typing import Callable, List, Optional

user32 = ctypes.windll.user32

def get_config_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(get_config_dir(), "config.json")

VK_MAP = {
    "ctrl": 0x11,
    "control": 0x11,
    "alt": 0x12,
    "shift": 0x10,
    "tab": 0x09,
    "space": 0x20,
    "~": 0xC0,
    "`": 0xC0,
    "º": 0xC0,
}

for i in range(1, 13):
    VK_MAP[f"f{i}"] = 0x70 + (i - 1)

def parse_combo_to_vks(combo_str: str) -> List[int]:
    """
    Convierte 'ctrl+x', 'f2', 'alt+x' en una lista de Virtual Key codes.
    """
    vks = []
    for part in combo_str.lower().split("+"):
        p = part.strip()
        if p in VK_MAP:
            vks.append(VK_MAP[p])
        elif len(p) == 1 and p.isalnum():
            vks.append(ord(p.upper()))
    return vks

class GlobalHotkeyManager:
    """
    Administrador de atajos globales usando GetAsyncKeyState de Win32.
    - Funciona dentro de League of Legends en cualquier modo (Ventana sin bordes, completa).
    - No depende de ganchos intrusivos ni es bloqueado por Riot Vanguard.
    - Consumo de CPU prácticamente nulo (~0.01%).
    """
    DEFAULT_HOTKEY = "ctrl+x"

    def __init__(self, on_hotkey_callback: Callable[[], None]):
        self.callback = on_hotkey_callback
        self.current_hotkey = self._load_saved_hotkey()
        self.vks = parse_combo_to_vks(self.current_hotkey)
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.thread.start()

    def _load_saved_hotkey(self) -> str:
        """Carga la tecla guardada en config.json o usa 'ctrl+x'."""
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    return cfg.get("hotkey", self.DEFAULT_HOTKEY)
            except Exception:
                pass
        return self.DEFAULT_HOTKEY

    def save_hotkey(self, combo_str: str):
        """Persiste la tecla elegida en config.json."""
        try:
            cfg = {}
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            cfg["hotkey"] = combo_str
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except Exception as e:
            print(f"[!] Error guardando config.json: {e}")

    def set_hotkey(self, combo_str: str) -> bool:
        """Cambia dinámicamente el atajo global."""
        new_vks = parse_combo_to_vks(combo_str)
        if not new_vks:
            print(f"[!] Tecla inválida: {combo_str}")
            return False

        with self.lock:
            self.current_hotkey = combo_str
            self.vks = new_vks
            self.save_hotkey(combo_str)

        print(f"[+] Atajo global activo: {combo_str.upper()}")
        return True

    def get_current_hotkey(self) -> str:
        return self.current_hotkey

    def _worker_loop(self):
        """Bucle de detección de pulsación por hardware con GetAsyncKeyState."""
        print(f"[+] Listener de atajo global iniciado para: {self.current_hotkey.upper()}")
        while not self.stop_event.is_set():
            with self.lock:
                target_vks = list(self.vks)

            if target_vks:
                all_down = True
                for vk in target_vks:
                    if not (user32.GetAsyncKeyState(vk) & 0x8000):
                        all_down = False
                        break

                if all_down:
                    try:
                        self.callback()
                    except Exception as e:
                        print(f"[!] Error en callback de atajo: {e}")

                    # Esperar a que el usuario suelte la tecla para no disparar en bucle
                    while not self.stop_event.is_set():
                        any_released = False
                        for vk in target_vks:
                            if not (user32.GetAsyncKeyState(vk) & 0x8000):
                                any_released = True
                                break
                        if any_released:
                            break
                        time.sleep(0.04)

            time.sleep(0.04)

    def stop(self):
        """Detiene el listener."""
        self.stop_event.set()
