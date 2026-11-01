import os
import sys
import ctypes
import subprocess
import threading
import time
import webview
from typing import Dict, Any, List, Optional

from lolalytics import LolalyticsClient
from lcu_connector import LCUConnector
from scout import ScoutService
from profile_service import ProfileService
from postgame_service import PostGameService
from hotkey_manager import GlobalHotkeyManager

class AppAPI:
    """
    API puente entre el Frontend HTML/CSS/JS y los módulos de Python.
    Expone funciones seguras que JavaScript puede llamar directamente.
    Todos los atributos internos llevan guion bajo '_' para que PyWebView
    no intente serializarlos y evitar recursión infinita.
    """
    def __init__(self):
        self._lolalytics = LolalyticsClient()
        self._lcu = LCUConnector()
        self._scout = ScoutService()
        self._profile_service = ProfileService(self._lcu)
        self._postgame_service = PostGameService(self._lcu)
        self._auto_runes_enabled = True
        self._last_applied_champ_id = None
        self._window = None
        self._ws_client = None
        
        # Inicializar Administrador de Hotkey Global Nativo Win32 (Vanguard-Safe)
        self._hotkey_mgr = GlobalHotkeyManager(on_hotkey_callback=self._on_hotkey_pressed)
        
        self._start_background_watcher()

    def _on_hotkey_pressed(self):
        print(f"[*] Atajo global detectado ({self._hotkey_mgr.get_current_hotkey().upper()})! Alternando ventana principal de LoL Companion...")
        self.toggle_main_window()

    def toggle_main_window(self):
        """
        Trae la ventana completa de la aplicación al frente por encima del juego
        o la minimiza si ya está activa.
        """
        user32 = ctypes.windll.user32
        
        # Buscar el HWND de la ventana principal
        hwnd = user32.FindWindowW(None, "LoL Companion - Lolalytics & LCU")
        if not hwnd:
            hwnds = []
            def enum_wnd(h, _):
                length = user32.GetWindowTextLengthW(h)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(h, buf, length + 1)
                    if "LoL Companion" in buf.value:
                        hwnds.append(h)
                return True
            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            user32.EnumWindows(WNDENUMPROC(enum_wnd), 0)
            if hwnds:
                hwnd = hwnds[0]

        if not hwnd and not self._window:
            print("[!] Ventana principal de LoL Companion no encontrada.")
            return

        fg = user32.GetForegroundWindow() if hwnd else 0
        is_iconic = bool(user32.IsIconic(hwnd)) if hwnd else False

        if hwnd and fg == hwnd and not is_iconic:
            # Minimizar para volver al juego
            user32.ShowWindow(hwnd, 6) # SW_MINIMIZE
            if self._window:
                try:
                    self._window.minimize()
                except Exception:
                    pass
            print("[*] Minimizando LoL Companion (volviendo al juego)...")
        else:
            # Traer al frente superpuesta al juego de LoL
            if hwnd:
                user32.AllowSetForegroundWindow(-1)
                user32.ShowWindow(hwnd, 9) # SW_RESTORE
                user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
                user32.SetForegroundWindow(hwnd)

            if self._window:
                try:
                    self._window.restore()
                    self._window.on_top = True
                    self._window.focus()
                except Exception:
                    pass

            print("[*] ¡LoL Companion traído al frente sobre la partida!")

    def get_configured_hotkey(self) -> str:
        """Devuelve la tecla de acceso rápido configurada actualmente."""
        return self._hotkey_mgr.get_current_hotkey()

    def set_hotkey_config(self, combo_str: str) -> bool:
        """Actualiza la tecla de acceso rápido global para abrir la app."""
        return self._hotkey_mgr.set_hotkey(combo_str)

    def get_tierlist(self, lane: str = "all") -> Dict[str, Any]:
        """Obtiene la Tier List de Lolalytics."""
        return self._lolalytics.get_tierlist(lane=lane)

    def get_champion_build(self, champion_name: str) -> Dict[str, Any]:
        """Obtiene la build completa (runas e items) de un campeón."""
        return self._lolalytics.get_champion_build(champion_name)

    def get_matchup(self, my_champion: str, enemy_champion: str, lane: str = "") -> Dict[str, Any]:
        """Obtiene el análisis de enfrentamiento directo entre dos campeones."""
        return self._lolalytics.get_matchup_analysis(my_champion, enemy_champion, lane or None)

    def get_champion_counters(self, champion_name: str, lane: str = "") -> Dict[str, Any]:
        """Obtiene la lista de los mejores y peores enfrentamientos (counters) de un campeón."""
        return self._lolalytics.get_champion_counters(champion_name, lane or None)

    def apply_runes_and_items(self, champion_name: str) -> bool:
        """Inyecta tanto la página de runas como el conjunto de objetos en la tienda de LoL."""
        if not self._lcu.session:
            self._lcu.connect()
        try:
            build_data = self._lolalytics.get_champion_build(champion_name)
            pop = build_data["most_popular"]["runes"]
            payload = pop["lcu_payload"]
            
            # 1. Inyectar runas
            rune_ok = self._lcu.apply_rune_page(
                payload["name"],
                payload["primaryStyleId"],
                payload["subStyleId"],
                payload["selectedPerkIds"]
            )
            
            # 2. Inyectar conjunto de objetos (Item Set)
            champ_id = None
            for cid, name in self._lcu._champions_cache.items():
                if name.lower() == champion_name.lower():
                    champ_id = cid
                    break
            
            self._lcu.inject_item_set_for_champion(champion_name, champ_id or 0, build_data)
            return rune_ok
        except Exception as e:
            print(f"[!] Error al aplicar runas e items: {e}")
            return False

    def apply_runes(self, page_name: str, primary_style_id: int, sub_style_id: int, selected_perk_ids: List[int]) -> bool:
        """Inyecta una página de runas directamente en el cliente de LoL."""
        if not self._lcu.session:
            self._lcu.connect()
        return self._lcu.apply_rune_page(page_name, primary_style_id, sub_style_id, selected_perk_ids)

    def get_client_status(self) -> Dict[str, Any]:
        """Consulta el estado actual de la conexión con el cliente de LoL."""
        if not self._lcu.session or not self._lcu.port:
            self._lcu.connect()

        if not self._lcu.session:
            return {"connected": False}

        summoner = self._lcu.get_current_summoner()
        if not summoner:
            return {"connected": False}

        name = summoner.get("gameName") or summoner.get("displayName", "Invocador")
        tag = summoner.get("tagLine", "")
        full_name = f"{name}#{tag}" if tag else name

        puuid = summoner.get("puuid")
        rank_str = "Unranked"
        if puuid:
            ranked_data = self._lcu.request("GET", f"/lol-ranked/v1/ranked-stats/{puuid}")
            if ranked_data:
                soloq = ranked_data.get("queueMap", {}).get("RANKED_SOLO_5x5", {})
                t = soloq.get("tier")
                if t and t != "UNRANKED":
                    rank_str = f"{t} {soloq.get('division', '')} ({soloq.get('leaguePoints', 0)} LP)"

        phase = self._lcu.request("GET", "/lol-gameflow/v1/gameflow-phase")
        champ_select = self._lcu.get_champ_select_session()

        in_game = phase in ("InProgress", "GameStart", "Reconnect")
        if not in_game:
            try:
                res_live = self._scout._live_session.get("https://127.0.0.1:2999/liveclientdata/activeplayername", timeout=0.3)
                if res_live.status_code == 200:
                    in_game = True
            except Exception:
                pass

        in_champ_select = (champ_select is not None) or (phase == "ChampSelect")

        return {
            "connected": True,
            "summoner_name": full_name,
            "soloq_rank": rank_str,
            "game_phase": phase,
            "in_champ_select": in_champ_select,
            "in_game": in_game
        }

    def get_lobby_scout(self, force: bool = False) -> Dict[str, Any]:
        """Scoutea a los jugadores de la partida activa (Champ Select o Pantalla de Carga / In-Game)."""
        return self._scout.scout_active_match(force=force)

    def get_user_profile(self) -> Dict[str, Any]:
        """Obtiene el perfil completo del invocador e historial de partidas estilo OP.GG."""
        return self._profile_service.get_full_profile()

    def get_postgame_autopsy(self, force: bool = False) -> Dict[str, Any]:
        """Obtiene la autopsia táctica y medallas de rendimiento de la última partida."""
        return self._postgame_service.analyze_last_game(force=force)

    def set_auto_runes(self, enabled: bool):
        """Activa o desactiva el inyector automático de runas."""
        self._auto_runes_enabled = enabled
        print(f"[*] Auto-Runas en segundo plano: {'ACTIVADO' if enabled else 'DESACTIVADO'}")

    def _start_background_watcher(self):
        """
        Monitorea el cliente local de LoL mediante WebSockets WAMP (0 ms de latencia, 0% CPU).
        Si el WebSocket se desconecta, mantiene un hilo ligero de respaldo.
        """
        def on_lcu_event(uri: str, data: Any, event_type: str):
            if "champ-select/v1/session" in uri and self._auto_runes_enabled:
                try:
                    status = self._lcu.get_my_champ_select_status()
                    if status and status.get("is_locked_in"):
                        champ_id = status.get("champion_id")
                        champ_name = status.get("champion_name")
                        role = status.get("role")
                        if champ_id and champ_id != self._last_applied_champ_id and champ_name:
                            print(f"[LCU WebSocket 0ms] Lock-in detectado: {champ_name} ({role})! Inyectando runas e Item Set...")
                            build_data = self._lolalytics.get_champion_build(champ_name)
                            pop = build_data["most_popular"]["runes"]
                            payload = pop["lcu_payload"]
                            self._lcu.apply_rune_page(
                                payload["name"],
                                payload["primaryStyleId"],
                                payload["subStyleId"],
                                payload["selectedPerkIds"]
                            )
                            self._lcu.inject_item_set_for_champion(champ_name, champ_id, build_data)
                            self._last_applied_champ_id = champ_id
                    elif not status:
                        self._last_applied_champ_id = None
                except Exception as e:
                    print(f"[!] Error procesando evento de ChampSelect: {e}")

        def watcher_loop():
            while True:
                try:
                    if not self._lcu.session:
                        self._lcu.connect()

                    if self._lcu.session:
                        # Iniciar listener de WebSockets WAMP si aún no está corriendo
                        if not self._ws_client:
                            self._ws_client = self._lcu.start_websocket_listener(on_lcu_event)

                        # Loop de respaldo HTTP cada 3 segundos
                        if self._auto_runes_enabled and not self._ws_client:
                            status = self._lcu.get_my_champ_select_status()
                            if status and status.get("is_locked_in"):
                                champ_id = status.get("champion_id")
                                champ_name = status.get("champion_name")
                                if champ_id and champ_id != self._last_applied_champ_id and champ_name:
                                    build_data = self._lolalytics.get_champion_build(champ_name)
                                    pop = build_data["most_popular"]["runes"]
                                    payload = pop["lcu_payload"]
                                    self._lcu.apply_rune_page(
                                        payload["name"],
                                        payload["primaryStyleId"],
                                        payload["subStyleId"],
                                        payload["selectedPerkIds"]
                                    )
                                    self._lcu.inject_item_set_for_champion(champ_name, champ_id, build_data)
                                    self._last_applied_champ_id = champ_id
                            elif not status:
                                self._last_applied_champ_id = None
                except Exception:
                    pass
                time.sleep(3)

        thread = threading.Thread(target=watcher_loop, daemon=True)
        thread.start()

def get_base_dir():
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.dirname(os.path.abspath(__file__))

def main():
    api = AppAPI()
    gui_dir = os.path.join(get_base_dir(), "gui")
    html_file = os.path.join(gui_dir, "index.html")

    window = webview.create_window(
        title="LoL Companion - Lolalytics & LCU",
        url=html_file,
        js_api=api,
        width=1180,
        height=760,
        min_size=(950, 600),
        background_color="#0b0e14"
    )
    api._window = window
    webview.start(debug=False)

if __name__ == "__main__":
    main()
