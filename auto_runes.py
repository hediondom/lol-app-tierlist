import time
import sys
from typing import Optional
from lcu_connector import LCUConnector
from lolalytics import LolalyticsClient
from scout import ScoutService

class AutoRuneService:
    """
    Servicio en segundo plano que monitorea la Seleccion de Campeones de LoL:
    1. Hace Scouting automatico de los 4 aliados al entrar al lobby (Rango, Rachas, Badges).
    2. Cuando el jugador fija su campeon (lock-in), aplica automaticamente las runas de Lolalytics.
    """
    def __init__(self, mode: str = "most_popular", riot_api_key: Optional[str] = None):
        """
        mode: 'most_popular' o 'highest_winrate'
        """
        self.mode = mode
        self.lcu = LCUConnector()
        self.lolalytics = LolalyticsClient()
        self.scout = ScoutService(riot_api_key=riot_api_key)
        self.last_applied_champ_id: Optional[int] = None
        self.lobby_scouted = False
        self.running = False

    def start(self, poll_interval: float = 1.5):
        self.running = True
        print("\n" + "=" * 60)
        print("     [AUTO-RUNAS ACTIVADO] - LOL COMPANION")
        print(f" Modo: {'Mas Popular' if self.mode == 'most_popular' else 'Mayor Winrate'}")
        print("=" * 60)
        print("[*] Esperando que entres a Seleccion de Campeones...")
        print("[*] Presiona Ctrl+C en cualquier momento para detener.\n")

        while self.running:
            try:
                # 1. Asegurar conexion con el cliente de LoL
                if not self.lcu.session or not self.lcu.port:
                    if not self.lcu.connect():
                        time.sleep(3)
                        continue

                # 2. Consultar estado en seleccion de campeon
                status = self.lcu.get_my_champ_select_status()

                if not status:
                    # No esta en seleccion de campeones actualmente
                    if self.last_applied_champ_id is not None or self.lobby_scouted:
                        print("\n[*] Seleccion de campeones terminada. Esperando siguiente partida...")
                        self.last_applied_champ_id = None
                        self.lobby_scouted = False
                    time.sleep(poll_interval)
                    continue

                # 3. Scouting del Lobby al entrar a Champ Select (1 sola vez por partida)
                if not self.lobby_scouted:
                    self.scout.scout_current_lobby()
                    self.lobby_scouted = True
                    print("\n[*] Vigilante activo: esperando que fijes tu campeon (Lock-in)...")

                # 4. Detectar si el jugador fijo un campeon para Auto-Runas
                is_locked = status["is_locked_in"]
                champ_id = status["champion_id"]
                champ_name = status["champion_name"]
                role = status["role"]

                if is_locked and champ_id and champ_id > 0:
                    # Si ya aplicamos runas a este campeon en este draft, no repetir
                    if self.last_applied_champ_id == champ_id:
                        time.sleep(poll_interval)
                        continue

                    print(f"\n[!] >>> CAMPEON FIJADO DETECTADO: {champ_name.upper()} (Rol: {role.upper()})! <<<")
                    self.apply_runes_for_champion(champ_name, role, champ_id=champ_id)
                    self.last_applied_champ_id = champ_id

                time.sleep(poll_interval)

            except KeyboardInterrupt:
                print("\n[*] Servicio de Auto-Runas detenido.")
                self.running = False
                break
            except Exception as e:
                # Si ocurre un error de red temporal, continuar el bucle
                time.sleep(poll_interval)

    def apply_runes_for_champion(self, champion_name: str, lane: str, champ_id: Optional[int] = None):
        print(f"[*] Consultando mejor build en Lolalytics para {champion_name}...")
        try:
            # Buscar en Lolalytics usando la linea asignada (si no es 'all')
            lane_filter = lane if lane in ["top", "jungle", "middle", "bottom", "support"] else None
            build_data = self.lolalytics.get_champion_build(champion_name, lane=lane_filter)
            
            chosen_build = build_data[self.mode]
            runes = chosen_build["runes"]
            payload = runes["lcu_payload"]

            page_name = f"Lolalytics - {champion_name}"
            print(f"[*] Inyectando pagina de runas en el cliente LoL...")

            success = self.lcu.apply_rune_page(
                page_name=page_name,
                primary_style_id=payload["primaryStyleId"],
                sub_style_id=payload["subStyleId"],
                selected_perk_ids=payload["selectedPerkIds"]
            )

            # Inyectar Item Set directamente en la tienda del juego
            item_set_success = self.lcu.inject_item_set_for_champion(champion_name, champ_id or 0, build_data)

            if success:
                print(f"[+] RUNAS APLICADAS CON EXITO EN TU CLIENTE!")
                print(f"    Rama Principal: {runes['primary_style_name']}")
                for p in runes["primary_runes"]:
                    print(f"      - {p['name']}")
                print(f"    Rama Secundaria: {runes['sub_style_name']}")
                for p in runes["secondary_runes"]:
                    print(f"      - {p['name']}")
                print(f"    Fragmentos:")
                for s in runes["shards"]:
                    print(f"      - {s['name']}")
                print(f"    Winrate de esta pagina: {chosen_build['winrate']}% ({chosen_build['games']:,} partidas)")
                
                # Mostrar items de recomendacion rapida
                core = [i['name'] for i in chosen_build['items']['core']]
                if core:
                    print(f"    Build recomendada: {' -> '.join(core)}")
                if item_set_success:
                    print(f"[+] OBJETOS INYECTADOS EN LA TIENDA DEL JUEGO (Abre la tienda con 'P' para verlos)")
                print("-" * 60)
            else:
                print("[X] No se pudo actualizar la pagina de runas en el cliente.")
        except Exception as e:
            print(f"[!] Error al procesar build de Lolalytics: {e}")

if __name__ == "__main__":
    mode_arg = "most_popular"
    if len(sys.argv) > 1 and sys.argv[1] == "--winrate":
        mode_arg = "highest_winrate"
    service = AutoRuneService(mode=mode_arg)
    service.start()
