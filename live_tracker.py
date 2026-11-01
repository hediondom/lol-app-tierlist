import time
import requests
import urllib3
from typing import Dict, Any, Optional

from lcu_connector import LCUConnector
from lolalytics import LolalyticsClient

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class LiveTracker:
    """
    Rastrea el estado en vivo de la partida de League of Legends conectando con:
    1. Riot Games Live Client Data API (https://127.0.0.1:2999/liveclientdata/)
    2. Local League Client Update (LCU) API
    3. Lolalytics para builds, matchups y counters.
    """
    LIVE_BASE_URL = "https://127.0.0.1:2999/liveclientdata"

    def __init__(self):
        self.session = requests.Session()
        self.session.verify = False
        self.lcu = LCUConnector()
        self.lolalytics = LolalyticsClient()
        self._cached_build: Optional[Dict[str, Any]] = None
        self._cached_champ: Optional[str] = None
        self._cached_matchup: Optional[Dict[str, Any]] = None
        self._cached_enemy: Optional[str] = None

    def get_live_game_stats(self) -> Optional[Dict[str, Any]]:
        """
        Consulta la API en vivo de Riot (puerto 2999) activa durante la partida.
        Devuelve CS en vivo, CS/minuto, KDA, oro y tiempo de juego.
        """
        try:
            # 1. Obtener tiempo de juego
            res_game = self.session.get(f"{self.LIVE_BASE_URL}/gamestats", timeout=0.8)
            if res_game.status_code != 200:
                return None
            gamestats = res_game.json()
            game_time = gamestats.get("gameTime", 0.0)

            # 2. Obtener datos del jugador activo
            res_player = self.session.get(f"{self.LIVE_BASE_URL}/activeplayer", timeout=0.8)
            if res_player.status_code != 200:
                return None
            active_player = res_player.json()
            summoner_name = active_player.get("summonerName", "")
            current_gold = int(active_player.get("currentGold", 0))
            level = active_player.get("level", 1)

            # 3. Obtener lista de jugadores para calcular CS y KDA
            res_list = self.session.get(f"{self.LIVE_BASE_URL}/playerlist", timeout=0.8)
            player_list = res_list.json() if res_list.status_code == 200 else []

            me = next((p for p in player_list if p.get("summonerName") == summoner_name), None)
            if not me and player_list:
                # Si no coincide summonerName exacto por Riot ID, intentar el primero o buscar
                me = player_list[0]

            champ_name = me.get("championName", "") if me else ""
            scores = me.get("scores", {}) if me else {}
            kills = scores.get("kills", 0)
            deaths = scores.get("deaths", 0)
            assists = scores.get("assists", 0)
            cs = scores.get("creepScore", 0)

            # Cálculo de CS / Minuto
            minutes = max(1.0, game_time / 60.0)
            cs_per_min = round(cs / minutes, 1)

            # Clasificación de CS
            if cs_per_min >= 8.5:
                cs_rating = "Challenger"
                cs_color = "#22c55e" # verde
            elif cs_per_min >= 7.0:
                cs_rating = "Diamante"
                cs_color = "#38bdf8" # celeste
            elif cs_per_min >= 5.5:
                cs_rating = "Oro / Platino"
                cs_color = "#f59e0b" # dorado/amarillo
            else:
                cs_rating = "Bajo CS"
                cs_color = "#ef4444" # rojo

            mins_int = int(game_time // 60)
            secs_int = int(game_time % 60)
            time_str = f"{mins_int:02d}:{secs_int:02d}"

            return {
                "in_live_game": True,
                "game_time_str": time_str,
                "game_time_seconds": game_time,
                "champion_name": champ_name,
                "summoner_name": summoner_name,
                "level": level,
                "gold": current_gold,
                "cs": cs,
                "cs_per_min": cs_per_min,
                "cs_rating": cs_rating,
                "cs_color": cs_color,
                "kills": kills,
                "deaths": deaths,
                "assists": assists,
                "kda_str": f"{kills}/{deaths}/{assists}"
            }
        except Exception:
            return None

    def get_overlay_state(self) -> Dict[str, Any]:
        """
        Calcula el estado integral para el Mini-Overlay Flotante:
        1. Si está jugando partida en vivo: devuelve CS/min, matchup en vivo, skills e items.
        2. Si está en Selección de Campeones: devuelve build y counter del rival.
        3. Si está en espera: estado del cliente y rango.
        """
        # 1. Intentar Live Game Data
        live_stats = self.get_live_game_stats()
        if live_stats:
            champ = live_stats["champion_name"]
            
            # Cargar build recomendada si cambió el campeón
            if champ and champ != self._cached_champ:
                try:
                    self._cached_build = self.lolalytics.get_champion_build(champ)
                    self._cached_champ = champ
                except Exception:
                    pass

            # Buscar rival de línea a través de LCU si es posible
            direct_matchup = None
            if not self.lcu.session:
                self.lcu.connect()

            if self.lcu.session:
                gameflow = self.lcu.request("GET", "/lol-gameflow/v1/session")
                if gameflow and gameflow.get("phase") in ("InProgress", "GameStart", "Reconnect"):
                    gdata = gameflow.get("gameData", {})
                    team_one = gdata.get("teamOne", [])
                    team_two = gdata.get("teamTwo", [])
                    
                    me_info = self.lcu.get_current_summoner()
                    my_puuid = me_info.get("puuid") if me_info else None
                    
                    my_team = team_one
                    enemy_team = team_two
                    if any(p.get("puuid") == my_puuid for p in team_two):
                        my_team = team_two
                        enemy_team = team_one

                    my_player = next((p for p in my_team if p.get("puuid") == my_puuid), None)
                    if my_player:
                        my_pos = my_player.get("selectedPosition", "").lower()
                        enemy_player = next((e for e in enemy_team if e.get("selectedPosition", "").lower() == my_pos and my_pos), None)
                        if enemy_player:
                            enemy_cid = enemy_player.get("championId", 0)
                            enemy_champ = self.lcu.get_champion_name(enemy_cid)
                            if enemy_champ and enemy_champ != self._cached_enemy:
                                try:
                                    self._cached_matchup = self.lolalytics.get_matchup_analysis(champ, enemy_champ, my_pos)
                                    self._cached_enemy = enemy_champ
                                except Exception:
                                    pass
                            direct_matchup = self._cached_matchup

            return {
                "mode": "in_game",
                "title": f"{live_stats['champion_name']} (Niv. {live_stats['level']})",
                "live_stats": live_stats,
                "matchup": direct_matchup or self._cached_matchup,
                "build": self._cached_build
            }

        # 2. Si no hay partida en vivo, consultar LCU (Champ Select o Lobby)
        if not self.lcu.session:
            self.lcu.connect()

        if self.lcu.session:
            phase = self.lcu.request("GET", "/lol-gameflow/v1/gameflow-phase")
            cs_status = self.lcu.get_my_champ_select_status()

            if cs_status and cs_status.get("in_champ_select"):
                champ_name = cs_status.get("champion_name")
                is_locked = cs_status.get("is_locked_in")
                
                build_data = None
                if champ_name and champ_name != "Eligiendo...":
                    if champ_name != self._cached_champ:
                        try:
                            self._cached_build = self.lolalytics.get_champion_build(champ_name)
                            self._cached_champ = champ_name
                        except Exception:
                            pass
                    build_data = self._cached_build

                return {
                    "mode": "champ_select",
                    "title": f"Draft: {champ_name or 'Eligiendo...'}",
                    "is_locked": is_locked,
                    "champion_name": champ_name,
                    "role": cs_status.get("role", "all"),
                    "build": build_data
                }

        # 3. Estado en espera (Idle / Esperando partida)
        summoner_name = "Invocador"
        rank_str = "Conectado"
        if self.lcu.session:
            s = self.lcu.get_current_summoner()
            if s:
                name = s.get("gameName") or s.get("displayName", "Invocador")
                tag = s.get("tagLine", "")
                summoner_name = f"{name}#{tag}" if tag else name
                puuid = s.get("puuid")
                if puuid:
                    ranked = self.lcu.request("GET", f"/lol-ranked/v1/ranked-stats/{puuid}")
                    if ranked:
                        soloq = ranked.get("queueMap", {}).get("RANKED_SOLO_5x5", {})
                        t = soloq.get("tier")
                        if t and t != "UNRANKED":
                            rank_str = f"{t} {soloq.get('division', '')} ({soloq.get('leaguePoints', 0)} LP)"

        return {
            "mode": "idle",
            "title": "Esperando partida...",
            "summoner_name": summoner_name,
            "rank": rank_str,
            "connected": bool(self.lcu.session)
        }
