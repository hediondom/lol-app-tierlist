import os
import re
import json
import base64
import ssl
import time
import threading
import requests
import urllib3
from typing import Optional, Dict, Any, List, Callable, Tuple
from ddragon import get_ddragon

try:
    import websocket
except ImportError:
    websocket = None
    print("[!] Módulo 'websocket-client' no disponible; se mantendrá polling HTTP.")

# Desactivar advertencias de certificados autofirmados del cliente local de LoL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class LCUWebSocketClient:
    """
    Cliente WebSocket nativo para el bus de eventos WAMP de League of Legends.
    Recibe notificaciones push en tiempo real (0 ms de retraso, 0% CPU en reposo).
    """
    def __init__(self, credentials_provider: Callable[[], Optional[Tuple[int, str]]], on_event_callback: Callable[[str, Any, str], None]):
        self.credentials_provider = credentials_provider
        self.on_event_callback = on_event_callback
        self.ws = None
        self.running = False
        self.thread = None

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
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
            # Las credenciales se releen en cada intento: si el cliente de LoL se reinicia,
            # el lockfile trae un puerto y una contraseña nuevos
            creds = self.credentials_provider()
            if creds:
                port, auth_token = creds
                try:
                    self.ws = websocket.WebSocketApp(
                        f"wss://127.0.0.1:{port}/",
                        header=["Authorization: Basic " + auth_token],
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
        # Catálogo de campeones de Data Dragon (se actualiza solo cuando sale un parche)
        self._ddragon = get_ddragon()

    def get_champion_name(self, champion_id: int) -> Optional[str]:
        """Obtiene el nombre en texto de un campeon a partir de su ID numerico."""
        return self._ddragon.champion_name(champion_id)

    def get_champion_folder_name(self, champion_id: int) -> Optional[str]:
        """Obtiene el nombre de carpeta para el campeon (ej. AurelionSol, MonkeyKing)."""
        return self._ddragon.champion_folder(champion_id)

    def get_champion_id(self, champion_name: str) -> Optional[int]:
        """Obtiene el ID numerico de un campeon a partir de su nombre (ej. 'Wukong' -> 62)."""
        return self._ddragon.champion_id(champion_name)

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

            port = int(parts[2])
            password = parts[3]
            protocol = parts[4]

            # Mismas credenciales que la sesión actual: no hace falta recrearla
            if self.session and port == self.port and password == self.password:
                return True

            session = requests.Session()
            session.verify = False
            auth_token = base64.b64encode(f"riot:{password}".encode()).decode()
            session.headers.update({
                "Authorization": f"Basic {auth_token}",
                "Accept": "application/json"
            })
            self.port, self.password, self.protocol, self.session = port, password, protocol, session
            return True
        except Exception:
            return False

    def _reset_session(self):
        """Descarta la sesión actual para que la próxima petición vuelva a leer el lockfile."""
        self.session = None
        self.port = None
        self.password = None

    def request(self, method: str, endpoint: str, **kwargs) -> Optional[Any]:
        """
        Realiza una peticion a la API del cliente local.
        Si el cliente se reinició (nuevo puerto/contraseña en el lockfile), la sesión vieja falla
        con error de conexión o 401: se descarta, se reconecta y se reintenta una vez.
        """
        for _ in range(2):
            if not self.session or not self.port:
                if not self.connect():
                    return None
            session, port = self.session, self.port
            if not session or not port:
                continue

            url = f"{self.protocol}://127.0.0.1:{port}{endpoint}"
            try:
                res = session.request(method, url, timeout=5, **kwargs)
                if res.status_code == 401:
                    self._reset_session()
                    continue
                if res.status_code in (200, 201):
                    return res.json()
                elif res.status_code == 204:
                    return True
                return None
            except requests.exceptions.ConnectionError:
                self._reset_session()
            except requests.exceptions.RequestException:
                return None
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

        # 2. Si no, creamos una nueva sin tocar las paginas personalizadas del usuario
        res = self.request("POST", "/lol-perks/v1/pages", json=payload)
        if res:
            return True

        # 3. Si no se pudo crear (limite de paginas alcanzado), reutilizamos la pagina editable activa.
        #    Nunca se borran paginas: si el payload es invalido, el PUT tambien falla y no se pierde nada.
        if editable_pages:
            active_page = next((p for p in editable_pages if p.get("current")), editable_pages[0])
            res = self.request("PUT", f"/lol-perks/v1/pages/{active_page['id']}", json=payload)
            if res:
                return True

        return False

    def create_item_set_blocks(self, build_data: Dict[str, Any], role_name: str = "") -> List[Dict[str, Any]]:
        """Crea los 7 bloques tácticos para una build específica."""
        pop = build_data.get("most_popular", {})
        items_data = pop.get("items", {})
        skill_prio = pop.get("skills", {}).get("priority", "Q>W>E")
        
        start_items = items_data.get("starting", [])
        core_items = items_data.get("core", [])
        
        role_tag = f" ({role_name})" if role_name else ""
        
        blocks = []
        # 1. Inicio Recomendado
        start_ids = [{"id": str(i["id"]), "count": 1} for i in start_items] if start_items else [{"id": "1055", "count": 1}, {"id": "2003", "count": 1}]
        blocks.append({
            "type": f"1. Inicio Recomendado{role_tag} & Visión",
            "items": start_ids + [{"id": "3340", "count": 1}]
        })

        # 2. Opciones de Botas
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
                "type": f"3. Core Build{role_tag} (Mayor WR • Max: {skill_prio})",
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
        return blocks

    def inject_multi_build_item_sets(self, champion_name: str, champion_id: int, multi_builds: Dict[str, Dict[str, Any]], active_role: str = "") -> bool:
        """
        Inyecta múltiples Item Sets para un campeón (ej: Lux Mid + Lux Support + Set Maestro Multi-Rol).
        Permite al jugador tener todas las variantes en el menú desplegable de la tienda de LoL.
        """
        try:
            folder_name = self.get_champion_folder_name(champion_id) or champion_name.replace(" ", "").replace("'", "")
            role_display_map = {
                "middle": "Mid",
                "mid": "Mid",
                "support": "Support",
                "utility": "Support",
                "top": "Top",
                "jungle": "Jungle",
                "bottom": "ADC",
                "adc": "ADC",
                "primary": "Principal"
            }

            created_sets: List[Dict[str, Any]] = []

            # 1. Crear un Item Set dedicado para cada rol
            for r_key, b_data in multi_builds.items():
                r_name = role_display_map.get(r_key.lower(), r_key.capitalize())
                is_active = (r_key.lower() == active_role.lower() or r_name.lower() == active_role.lower())
                blocks = self.create_item_set_blocks(b_data, role_name=r_name)

                created_sets.append({
                    "title": f"Lolalytics - {champion_name} ({r_name})",
                    "associatedChampions": [champion_id] if champion_id else [],
                    "associatedMaps": [11, 12],
                    "map": "any",
                    "mode": "any",
                    "preferredItemSlots": [],
                    "sortrank": 1 if is_active else 2,
                    "startedFrom": "blank",
                    "type": "custom",
                    "blocks": blocks
                })

            # 2. Si hay más de un rol, crear además un Item Set Maestro Combinado "Multi-Rol / Flex"
            if len(multi_builds) > 1:
                combined_blocks = []
                for r_key, b_data in multi_builds.items():
                    r_name = role_display_map.get(r_key.lower(), r_key.capitalize())
                    pop = b_data.get("most_popular", {})
                    items_data = pop.get("items", {})
                    skill_prio = pop.get("skills", {}).get("priority", "Q>W>E")
                    start_items = items_data.get("starting", [])
                    core_items = items_data.get("core", [])

                    start_ids = [{"id": str(i["id"]), "count": 1} for i in start_items] if start_items else [{"id": "1055", "count": 1}, {"id": "2003", "count": 1}]
                    combined_blocks.append({
                        "type": f"1. Inicio Recomendado ({r_name})",
                        "items": start_ids + [{"id": "3340", "count": 1}]
                    })
                    if core_items:
                        combined_blocks.append({
                            "type": f"3. Core Build ({r_name} • Max: {skill_prio})",
                            "items": [{"id": str(i["id"]), "count": 1} for i in core_items]
                        })

                # Añadir los bloques situacionales universales
                first_build = next(iter(multi_builds.values()))
                shared_blocks = self.create_item_set_blocks(first_build)
                for sb in shared_blocks:
                    if "Botas" in sb["type"] or "Situacional" in sb["type"] or "Consumibles" in sb["type"]:
                        combined_blocks.append(sb)

                created_sets.append({
                    "title": f"Lolalytics - {champion_name} (Multi-Rol / Flex)",
                    "associatedChampions": [champion_id] if champion_id else [],
                    "associatedMaps": [11, 12],
                    "map": "any",
                    "mode": "any",
                    "preferredItemSlots": [],
                    "sortrank": 3,
                    "startedFrom": "blank",
                    "type": "custom",
                    "blocks": combined_blocks
                })

            # Sincronización 1: Vía API local del cliente LoL
            try:
                summoner = self.get_current_summoner()
                if summoner and summoner.get("summonerId"):
                    sum_id = summoner["summonerId"]
                    existing = self.request("GET", f"/lol-item-sets/v1/item-sets/{sum_id}/sets") or {"itemSets": []}
                    # Solo los sets de este campeón: "Lolalytics - Vi" no debe borrar los de Viego o Viktor
                    own_title = f"Lolalytics - {champion_name}"
                    sets_list = [s for s in existing.get("itemSets", [])
                                 if s.get("title", "") != own_title and not s.get("title", "").startswith(own_title + " (")]
                    sets_list.extend(created_sets)
                    existing["itemSets"] = sets_list
                    self.request("PUT", f"/lol-item-sets/v1/item-sets/{sum_id}/sets", json=existing)
            except Exception as e:
                print(f"[!] Error sincronizando Item Sets vía LCU API: {e}")

            # Sincronización 2: Vía archivos locales en Config/Champions/{folder}/Recommended/
            lock_path = self.find_lockfile()
            base_dir = os.path.dirname(lock_path) if lock_path else r"C:\Riot Games\League of Legends"
            target_dir = os.path.join(base_dir, "Config", "Champions", folder_name, "Recommended")
            os.makedirs(target_dir, exist_ok=True)

            for s in created_sets:
                clean_title = re.sub(r'[^a-zA-Z0-9_\-]', '_', s['title'])
                target_file = os.path.join(target_dir, f"{clean_title}.json")
                with open(target_file, "w", encoding="utf-8") as f:
                    json.dump(s, f, indent=2)

            print(f"[+] {len(created_sets)} Item Sets enriquecidos inyectados para {champion_name}")
            return True
        except Exception as e:
            print(f"[!] Error al inyectar Item Sets: {e}")
            return False

    def inject_item_set_for_champion(self, champion_name: str, champion_id: int, build_data: Dict[str, Any], role_name: str = "") -> bool:
        """Compatibilidad hacia atrás: inyecta un set o redirige a multi-build."""
        role_key = role_name.lower() if role_name else "primary"
        return self.inject_multi_build_item_sets(champion_name, champion_id, {role_key: build_data}, active_role=role_name)

    def _websocket_credentials(self) -> Optional[Tuple[int, str]]:
        """Relee el lockfile y devuelve (puerto, token) vigentes para el WebSocket."""
        if not self.connect():
            return None
        port, password = self.port, self.password
        if not port or not password:
            return None
        auth_token = base64.b64encode(f"riot:{password}".encode("utf-8")).decode("utf-8")
        return port, auth_token

    def start_websocket_listener(self, on_event_callback: Callable[[str, Any, str], None]) -> Optional[LCUWebSocketClient]:
        """
        Inicia el cliente WebSocket WAMP para recibir notificaciones push en tiempo real.
        Devuelve None si 'websocket-client' no está instalado, para que se use el polling HTTP.
        """
        if websocket is None or not self.connect():
            return None

        ws_client = LCUWebSocketClient(self._websocket_credentials, on_event_callback)
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
