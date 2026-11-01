import os
import sys
import re
import json
import base64
import ssl
import time
import threading
import requests
import urllib3
from typing import Optional, Dict, Any, List, Callable

try:
    import websocket
except ImportError:
    websocket = None

# Desactivar advertencias de certificados autofirmados del cliente local de LoL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class LCUWebSocketClient:
    """
    Cliente WebSocket nativo para el bus de eventos WAMP de League of Legends.
    Recibe notificaciones push en tiempo real (0 ms de retraso, 0% CPU en reposo).
    """
    def __init__(self, port: int, auth_token: str, on_event_callback: Callable[[str, Any, str], None]):
        self.port = port
        self.auth_token = auth_token
        self.on_event_callback = on_event_callback
        self.ws = None
        self.running = False
        self.thread = None

    def start(self):
        if not websocket:
            print("[!] Módulo 'websocket-client' no disponible; se mantendrá polling HTTP.")
            return
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        url = f"wss://127.0.0.1:{self.port}/"
        headers = ["Authorization: Basic " + self.auth_token]

        def on_open(ws):
            # Suscribirse al bus general de eventos WAMP del LCU
            try:
                ws.send(json.dumps([5, "OnJsonApiEvent"]))
                print("[+] Conectado al bus de eventos WebSocket del cliente LoL (0ms Latencia)")
            except Exception as e:
                print(f"[!] Error suscribiendo a eventos WebSocket: {e}")

        def on_message(ws, message):
            if not message:
                return
            try:
                payload = json.loads(message)
                if isinstance(payload, list) and len(payload) >= 3 and payload[1] == "OnJsonApiEvent":
                    ev = payload[2]
                    self.on_event_callback(ev.get("uri", ""), ev.get("data"), ev.get("eventType", ""))
            except Exception:
                pass

        while self.running:
            try:
                self.ws = websocket.WebSocketApp(
                    url,
                    header=headers,
                    on_open=on_open,
                    on_message=on_message
                )
                self.ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
            except Exception:
                pass
            time.sleep(3)

    def stop(self):
        self.running = False
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass

class LCUConnector:
    """
    Conector local con el cliente de League of Legends en ejecucion.
    Lee el archivo 'lockfile' para autenticacion y gestiona Champ Select y Runas.
    """
    DEFAULT_PATHS = [
        r"C:\Riot Games\League of Legends",
        r"D:\Riot Games\League of Legends",
        r"E:\Riot Games\League of Legends",
    ]

    def __init__(self, custom_path: Optional[str] = None):
        self.client_path = custom_path
        self.port: Optional[int] = None
        self.password: Optional[str] = None
        self.protocol: str = "https"
        self.session: Optional[requests.Session] = None
        self._champions_cache: Dict[int, str] = {}
        self._champions_folder_cache: Dict[int, str] = {}
        self._load_champions_cache()

    def _load_champions_cache(self):
        """Carga o descarga el mapeo de championId -> Nombre desde DataDragon."""
        base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        cache_file = os.path.join(base_dir, "champions_cache.json")
        cache_folder_file = os.path.join(base_dir, "champions_folder_cache.json")
        if os.path.isfile(cache_file) and os.path.isfile(cache_folder_file):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._champions_cache = {int(k): v for k, v in data.items()}
                with open(cache_folder_file, "r", encoding="utf-8") as f:
                    folder_data = json.load(f)
                    self._champions_folder_cache = {int(k): v for k, v in folder_data.items()}
                return
            except Exception:
                pass

        # Si no esta en disco, intentar descargarlo de DataDragon
        try:
            ver = requests.get("https://ddragon.leagueoflegends.com/api/versions.json", timeout=5).json()[0]
            champ_data = requests.get(f"https://ddragon.leagueoflegends.com/cdn/{ver}/data/en_US/champion.json", timeout=5).json()["data"]
            self._champions_cache = {int(c["key"]): c["name"] for c in champ_data.values()}
            self._champions_folder_cache = {int(c["key"]): c["id"] for c in champ_data.values()}
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(self._champions_cache, f, indent=2)
            with open(cache_folder_file, "w", encoding="utf-8") as f:
                json.dump(self._champions_folder_cache, f, indent=2)
        except Exception as e:
            print(f"[!] No se pudo cargar el catalogo de campeones de DataDragon: {e}")

    def get_champion_name(self, champion_id: int) -> Optional[str]:
        """Obtiene el nombre en texto de un campeon a partir de su ID numerico."""
        return self._champions_cache.get(champion_id)

    def get_champion_folder_name(self, champion_id: int) -> Optional[str]:
        """Obtiene el nombre de carpeta para el campeon (ej. AurelionSol, MonkeyKing)."""
        return self._champions_folder_cache.get(champion_id)

    def find_lockfile(self) -> Optional[str]:
        """Busca el archivo lockfile en las rutas conocidas."""
        paths_to_check = [self.client_path] if self.client_path else self.DEFAULT_PATHS
        for folder in paths_to_check:
            if not folder:
                continue
            lock_path = os.path.join(folder, "lockfile")
            if os.path.isfile(lock_path):
                return lock_path
        return None

    def connect(self) -> bool:
        """Intenta conectarse al cliente de LoL leyendo el lockfile."""
        lock_path = self.find_lockfile()
        if not lock_path:
            return False

        try:
            with open(lock_path, "r", encoding="utf-8") as f:
                content = f.read().strip()

            parts = content.split(":")
            if len(parts) < 5:
                return False

            self.port = int(parts[2])
            self.password = parts[3]
            self.protocol = parts[4]

            self.session = requests.Session()
            self.session.verify = False
            auth_token = base64.b64encode(f"riot:{self.password}".encode()).decode()
            self.session.headers.update({
                "Authorization": f"Basic {auth_token}",
                "Accept": "application/json"
            })
            return True
        except Exception:
            return False

    def request(self, method: str, endpoint: str, **kwargs) -> Optional[Any]:
        """Realiza una peticion a la API del cliente local."""
        if not self.session or not self.port:
            if not self.connect():
                return None

        url = f"{self.protocol}://127.0.0.1:{self.port}{endpoint}"
        try:
            res = self.session.request(method, url, timeout=5, **kwargs)
            if res.status_code in (200, 201):
                return res.json()
            elif res.status_code == 204:
                return True
            return None
        except requests.exceptions.RequestException:
            return None

    def get_current_summoner(self) -> Optional[Dict[str, Any]]:
        """Obtiene la informacion del invocador conectado actualmente."""
        return self.request("GET", "/lol-summoner/v1/current-summoner")

    def get_champ_select_session(self) -> Optional[Dict[str, Any]]:
        """Obtiene los datos de la seleccion de campeon en curso."""
        return self.request("GET", "/lol-champ-select/v1/session")

    def get_my_champ_select_status(self) -> Optional[Dict[str, Any]]:
        """
        Analiza el estado del jugador local en la seleccion de campeones actual.
        Retorna:
          - in_champ_select: bool
          - cell_id: int
          - role: str (ej. 'top', 'jungle', 'middle', 'bottom', 'utility')
          - champion_id: int (fijado/locked in)
          - pick_intent_id: int (en hover, no fijado aun)
          - champion_name: str
          - is_locked_in: bool
        """
        session = self.get_champ_select_session()
        if not session:
            return None

        local_cell_id = session.get("localPlayerCellId")
        my_team = session.get("myTeam", [])
        
        me = next((p for p in my_team if p.get("cellId") == local_cell_id), None)
        if not me:
            return None

        champ_id = me.get("championId", 0)
        pick_intent = me.get("championPickIntent", 0)
        role = me.get("assignedPosition", "all").lower()
        if role == "utility":
            role = "support"

        # Comprobar si ya esta fijado (lock-in completado)
        # 1. En draft normal/ranked: en 'actions' la accion propia de pick tiene completed == True
        # 2. En ARAM o Blind: championId > 0 inmediatamente
        is_locked = False
        if champ_id > 0:
            is_locked = True
        
        for action_group in session.get("actions", []):
            for action in action_group:
                if action.get("actorCellId") == local_cell_id and action.get("type") == "pick":
                    if action.get("completed"):
                        is_locked = True
                        champ_id = action.get("championId", champ_id)

        target_id = champ_id if is_locked else pick_intent
        target_name = self.get_champion_name(target_id) if target_id else None

        return {
            "in_champ_select": True,
            "cell_id": local_cell_id,
            "role": role,
            "champion_id": champ_id,
            "pick_intent_id": pick_intent,
            "champion_name": target_name,
            "is_locked_in": is_locked
        }

    def apply_rune_page(self, page_name: str, primary_style_id: int, sub_style_id: int, selected_perk_ids: List[int]) -> bool:
        """
        Crea o actualiza una pagina de runas en el cliente local.
        Maneja inteligentemente las paginas existentes para no saturar el limite de paginas.
        """
        pages = self.request("GET", "/lol-perks/v1/pages")
        if pages is None:
            return False

        editable_pages = [p for p in pages if p.get("isEditable")]

        payload = {
            "name": page_name,
            "primaryStyleId": primary_style_id,
            "subStyleId": sub_style_id,
            "selectedPerkIds": selected_perk_ids,
            "current": True
        }

        # 1. Si ya existe una pagina creada por nuestra app, la actualizamos
        existing_app_page = next((p for p in editable_pages if p.get("name", "").startswith("Lolalytics")), None)
        if existing_app_page:
            page_id = existing_app_page["id"]
            res = self.request("PUT", f"/lol-perks/v1/pages/{page_id}", json=payload)
            if res:
                return True

        # 2. Si no, pero hay alguna pagina editable activa o disponible, la sobreescribimos
        if editable_pages:
            # Preferir la pagina actualmente activa
            active_page = next((p for p in editable_pages if p.get("current")), editable_pages[0])
            page_id = active_page["id"]
            res = self.request("PUT", f"/lol-perks/v1/pages/{page_id}", json=payload)
            if res:
                return True

        # 3. Si no pudimos actualizar ninguna, intentamos crear una nueva
        res = self.request("POST", "/lol-perks/v1/pages", json=payload)
        if res:
            return True

        # 4. Si fallo por limite maximo de paginas, borramos la primera editable y creamos
        if editable_pages:
            self.request("DELETE", f"/lol-perks/v1/pages/{editable_pages[0]['id']}")
            res = self.request("POST", "/lol-perks/v1/pages", json=payload)
            return res is not None

        return False

    def inject_item_set_for_champion(self, champion_name: str, champion_id: int, build_data: Dict[str, Any]) -> bool:
        """
        Inyecta el conjunto de objetos (Item Set) enriquecido con bloques tácticos situacionales:
        - 1. Inicio Recomendado & Visión
        - 2. Opciones de Botas (según el rival: Tabis, Mercurio, Jonias, etc.)
        - 3. Core Build (Mayor Winrate en Lolalytics)
        - 4. Situacional: Anti-Curación (Heridas Graves)
        - 5. Situacional: Anti-Tanques & Penetración
        - 6. Situacional: Supervivencia & Anti-Burst
        - 7. Consumibles & Elixires de Late Game
        
        Se sincroniza tanto en memoria a través de la API del cliente (/lol-item-sets/v1/)
        como en disco en la carpeta Config/Champions/ para persistencia total.
        """
        try:
            folder_name = self.get_champion_folder_name(champion_id) or champion_name.replace(" ", "").replace("'", "")
            
            pop = build_data.get("most_popular", {})
            items_data = pop.get("items", {})
            skill_prio = pop.get("skills", {}).get("priority", "Q>W>E")
            
            start_items = items_data.get("starting", [])
            core_items = items_data.get("core", [])
            situational_items = items_data.get("situational", [])
            
            blocks = []
            # 1. Inicio Recomendado
            start_ids = [{"id": str(i["id"]), "count": 1} for i in start_items] if start_items else [{"id": "1055", "count": 1}, {"id": "2003", "count": 1}]
            blocks.append({
                "type": "1. Inicio Recomendado & Visión",
                "items": start_ids + [{"id": "3340", "count": 1}]
            })

            # 2. Opciones de Botas Tácticas
            blocks.append({
                "type": "2. Opciones de Botas (Elige según el rival)",
                "items": [
                    {"id": "3047", "count": 1}, # Punteras de Acero (Tabis - vs AD)
                    {"id": "3111", "count": 1}, # Botas de Mercurio (vs AP / CC)
                    {"id": "3158", "count": 1}, # Jonias (Vel. de Habilidad / CDR)
                    {"id": "3020", "count": 1}, # Hechicero (Penetración Mágica)
                    {"id": "3006", "count": 1}, # Berserker (Velocidad de Ataque)
                    {"id": "3009", "count": 1}  # Rapidez (vs Ralentizaciones)
                ]
            })

            # 3. Core Build Principal
            if core_items:
                blocks.append({
                    "type": f"3. Core Build (Mayor Winrate • Max: {skill_prio})",
                    "items": [{"id": str(i["id"]), "count": 1} for i in core_items]
                })

            # 4. Situacional: Anti-Curación
            blocks.append({
                "type": "4. Situacional: Anti-Curación (Heridas Graves)",
                "items": [
                    {"id": "3123", "count": 1}, # Llamado del Verdugo
                    {"id": "3033", "count": 1}, # Recordatorio Mortal
                    {"id": "3076", "count": 1}, # Chaleco de Zarzas
                    {"id": "3075", "count": 1}, # Malla de Espinas
                    {"id": "3916", "count": 1}, # Orbe del Olvido
                    {"id": "3165", "count": 1}  # Morellonomicon
                ]
            })

            # 5. Situacional: Anti-Tanques & Penetración
            blocks.append({
                "type": "5. Situacional: Anti-Tanques & Penetración",
                "items": [
                    {"id": "3036", "count": 1}, # Lord Dominik
                    {"id": "3135", "count": 1}, # Bastón del Vacío
                    {"id": "3137", "count": 1}, # Criptoflorecer
                    {"id": "3153", "count": 1}, # Rey Arruinado
                    {"id": "6694", "count": 1}, # Rencor de Serylda
                    {"id": "6653", "count": 1}  # Tormento de Liandry
                ]
            })

            # 6. Situacional: Supervivencia & Anti-Burst
            blocks.append({
                "type": "6. Situacional: Supervivencia & Anti-Burst",
                "items": [
                    {"id": "3157", "count": 1}, # Reloj de Arena de Zhonya
                    {"id": "3026", "count": 1}, # Ángel Guardián
                    {"id": "3140", "count": 1}, # Fajín de Mercurio (QSS)
                    {"id": "3139", "count": 1}, # Cimitarra Mercurial
                    {"id": "3156", "count": 1}, # Fauces de Malmortius
                    {"id": "3102", "count": 1}, # Velo de Banshee
                    {"id": "3053", "count": 1}  # Guantelete de Sterak
                ]
            })

            # 7. Consumibles & Elixires
            blocks.append({
                "type": "7. Consumibles & Elixires de Late Game",
                "items": [
                    {"id": "2055", "count": 1}, # Guardián de Control
                    {"id": "2031", "count": 1}, # Poción Reutilizable
                    {"id": "2138", "count": 1}, # Elixir de Hierro
                    {"id": "2139", "count": 1}, # Elixir de Brujería
                    {"id": "2140", "count": 1}  # Elixir de Cólera
                ]
            })
            
            item_set = {
                "title": f"Lolalytics - {champion_name}",
                "associatedChampions": [champion_id] if champion_id else [],
                "associatedMaps": [11, 12],
                "map": "any",
                "mode": "any",
                "preferredItemSlots": [],
                "sortrank": 1,
                "startedFrom": "blank",
                "type": "custom",
                "blocks": blocks
            }

            # Sincronización 1: Vía API local del cliente LoL
            try:
                summoner = self.get_current_summoner()
                if summoner and summoner.get("summonerId"):
                    sum_id = summoner["summonerId"]
                    existing = self.request("GET", f"/lol-item-sets/v1/item-sets/{sum_id}/sets") or {"itemSets": []}
                    sets_list = [s for s in existing.get("itemSets", []) if s.get("title") != item_set["title"]]
                    sets_list.append(item_set)
                    existing["itemSets"] = sets_list
                    self.request("PUT", f"/lol-item-sets/v1/item-sets/{sum_id}/sets", json=existing)
            except Exception:
                pass
            
            # Sincronización 2: Vía archivo local en Config/Champions/
            lock_path = self.find_lockfile()
            base_dir = os.path.dirname(lock_path) if lock_path else r"C:\Riot Games\League of Legends"
            target_dir = os.path.join(base_dir, "Config", "Champions", folder_name, "Recommended")
            os.makedirs(target_dir, exist_ok=True)
            
            target_file = os.path.join(target_dir, "Lolalytics.json")
            with open(target_file, "w", encoding="utf-8") as f:
                json.dump(item_set, f, indent=2)
            
            print(f"[+] Item Set Enriquecido inyectado exitosamente para {champion_name} (7 Bloques Tácticos)")
            return True
        except Exception as e:
            print(f"[!] Error al inyectar Item Set: {e}")
            return False

    def start_websocket_listener(self, on_event_callback: Callable[[str, Any, str], None]) -> Optional[LCUWebSocketClient]:
        """Inicia el cliente WebSocket WAMP para recibir notificaciones push en tiempo real."""
        if not self.session or not self.port or not self.password:
            if not self.connect():
                return None

        auth_token = base64.b64encode(f"riot:{self.password}".encode("utf-8")).decode("utf-8")
        ws_client = LCUWebSocketClient(self.port, auth_token, on_event_callback)
        ws_client.start()
        return ws_client

if __name__ == "__main__":
    connector = LCUConnector()
    print("[*] Probando conector LCU...")
    if connector.connect():
        print(f"[+] Conectado al cliente en el puerto {connector.port}!")
        status = connector.get_my_champ_select_status()
        if status:
            print("[+] Estado de Seleccion de Campeones:")
            print(f"    Rol: {status['role']}")
            print(f"    Campeon: {status['champion_name']} (Fijado: {status['is_locked_in']})")
        else:
            print("[-] No estas en seleccion de campeones.")
    else:
        print("[-] Cliente de LoL no detectado.")
