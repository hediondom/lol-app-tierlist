import os
import sys
import json
import ctypes
from ctypes import wintypes
import threading
from typing import Callable, Tuple, Optional

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

def get_config_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(get_config_dir(), "config.json")

# Constantes Win32
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000  # Evita disparos repetidos mientras se mantiene presionada

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_USER = 0x0400
WM_RELOAD_HOTKEY = WM_USER + 101

HOTKEY_ID = 1

VK_MAP = {
    "tab": 0x09,
    "space": 0x20,
    "~": 0xC0,
    "`": 0xC0,
    "º": 0xC0,
}
for i in range(1, 13):
    VK_MAP[f"f{i}"] = 0x70 + (i - 1)

def parse_combo(combo_str: str) -> Tuple[int, int]:
    """
    Convierte 'ctrl+x', 'f2', 'alt+x' en (modifiers, vk_code).
    """
    modifiers = MOD_NOREPEAT
    vk = 0
    parts = [p.strip().lower() for p in combo_str.split("+") if p.strip()]

    for p in parts:
        if p in ("ctrl", "control"):
            modifiers |= MOD_CONTROL
        elif p == "alt":
            modifiers |= MOD_ALT
        elif p == "shift":
            modifiers |= MOD_SHIFT
        elif p == "win":
            modifiers |= MOD_WIN
        elif p in VK_MAP:
            vk = VK_MAP[p]
        elif len(p) == 1 and p.isalnum():
            vk = ord(p.upper())

    return modifiers, vk

class GlobalHotkeyManager:
    """
    Administrador de atajos globales nativo Win32 usando RegisterHotKey y cola de mensajes.
    
    100% COMPLIANT CON RIOT GAMES & VANGUARD:
    - No utiliza bucles continuos de GetAsyncKeyState (que son alertados por la heurística de Vanguard).
    - Basado en eventos puros del sistema operativo mediante GetMessageW en hilo independiente.
    - Consumo de CPU exactamente 0% en reposo.
    """
    # RegisterHotKey se queda con la combinación en todo Windows: evitar atajos
    # de uso común como Ctrl+X (Cortar)
    DEFAULT_HOTKEY = "ctrl+shift+x"

    def __init__(self, on_hotkey_callback: Callable[[], None]):
        self.callback = on_hotkey_callback
        self.current_hotkey = self._load_saved_hotkey()
        self.modifiers, self.vk = parse_combo(self.current_hotkey)
        self.thread_id: Optional[int] = None
        self.ready_event = threading.Event()
        self.lock = threading.Lock()
        # Cambio de atajo pendiente: lo aplica el hilo de mensajes y devuelve el resultado
        self._pending_hotkey: Optional[Tuple[str, int, int]] = None
        self._reload_done = threading.Event()
        self._reload_ok = False

        self.thread = threading.Thread(target=self._msg_loop, daemon=True)
        self.thread.start()
        self.ready_event.wait(timeout=2.0)

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
        """
        Cambia dinámicamente el atajo global notificando al hilo de mensajes.
        Devuelve False si la combinación no es válida o si Windows no deja registrarla
        (por ejemplo, porque otra aplicación ya la usa); en ese caso se mantiene el atajo anterior.
        """
        mods, vk = parse_combo(combo_str)
        if not vk:
            print(f"[!] Tecla inválida o no soportada: {combo_str}")
            return False
        if not self.thread_id:
            return False

        # El lock serializa cambios simultáneos. RegisterHotKey tiene que ejecutarse
        # en el hilo dueño de la cola de mensajes, así que se espera su respuesta
        with self.lock:
            self._pending_hotkey = (combo_str, mods, vk)
            self._reload_done.clear()
            user32.PostThreadMessageW(self.thread_id, WM_RELOAD_HOTKEY, 0, 0)
            ok = self._reload_done.wait(timeout=2.0) and self._reload_ok

        if not ok:
            print(f"[!] No se pudo registrar {combo_str.upper()} (¿ya la usa otra aplicación?). Se mantiene {self.current_hotkey.upper()}.")
            return False

        self.save_hotkey(combo_str)
        print(f"[+] Atajo global actualizado: {combo_str.upper()} (Vanguard-Safe Win32 Event)")
        return True

    def get_current_hotkey(self) -> str:
        return self.current_hotkey

    def _msg_loop(self):
        """Hilo dedicado con bomba de mensajes Win32 para RegisterHotKey."""
        self.thread_id = kernel32.GetCurrentThreadId()

        # Registrar atajo inicial
        success = user32.RegisterHotKey(None, HOTKEY_ID, self.modifiers, self.vk)
        if success:
            print(f"[+] Atajo global activo vía RegisterHotKey (Win32 Event): {self.current_hotkey.upper()}")
        else:
            print(f"[!] Advertencia: No se pudo registrar {self.current_hotkey.upper()} vía RegisterHotKey (¿ya en uso?).")

        self.ready_event.set()

        msg = wintypes.MSG()
        # GetMessageW bloquea sin uso de CPU hasta que Windows entrega un mensaje
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == WM_HOTKEY:
                try:
                    self.callback()
                except Exception as e:
                    print(f"[!] Error ejecutando callback de atajo: {e}")
            elif msg.message == WM_RELOAD_HOTKEY and self._pending_hotkey:
                combo_str, mods, vk = self._pending_hotkey
                user32.UnregisterHotKey(None, HOTKEY_ID)
                if user32.RegisterHotKey(None, HOTKEY_ID, mods, vk):
                    self.current_hotkey, self.modifiers, self.vk = combo_str, mods, vk
                    self._reload_ok = True
                else:
                    # Combinación ocupada: volver a registrar el atajo anterior
                    user32.RegisterHotKey(None, HOTKEY_ID, self.modifiers, self.vk)
                    self._reload_ok = False
                self._reload_done.set()
            
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        user32.UnregisterHotKey(None, HOTKEY_ID)

    def stop(self):
        """Detiene el listener cerrando la cola de mensajes."""
        if self.thread_id:
            user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)
