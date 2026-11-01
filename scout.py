import os
import requests
import urllib3
from typing import Dict, Any, List, Optional, Tuple
from lcu_connector import LCUConnector
from riot_api import RiotAPIClient
from lolalytics import LolalyticsClient

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class ScoutService:
    """
    Servicio de Scouting de Lobby y Aliados estilo Porofessor / Mobalytics.
    Analiza a los compañeros de equipo en Selección de Campeones:
    - Rango en SoloQ y Flex (Tier, División, LP)
    - Racha actual (Victorias / Derrotas consecutivas)
    - Winrate reciente (últimas 10-20 partidas)
    - Campeones más jugados recientemente
    - Etiquetas / Badges (🔥 En Racha, ❄️ Tilt Warning, ⚠️ Autofill, etc.)
    """
    def __init__(self, riot_api_key: Optional[str] = None):
        self.lcu = LCUConnector()
        self.lolalytics = LolalyticsClient()
        self.api_key = riot_api_key or os.environ.get("RIOT_API_KEY", "")
        self.riot_api = RiotAPIClient(api_key=self.api_key) if self.api_key else None
        self._cached_game_data: Optional[Dict[str, Any]] = None
        self._cached_game_id: Optional[int] = None
        self._live_session = requests.Session()
        self._live_session.verify = False

    def scout_puuid(self, puuid: str, summoner_name: Optional[str] = None, assigned_position: str = "") -> Dict[str, Any]:
        """
        Analiza a un jugador por su PUUID utilizando las APIs locales del LCU
        y complementando con la Riot API oficial.
        """
        if not self.lcu.session or not self.lcu.port:
            self.lcu.connect()

        # 1. Obtener nombre del invocador si no fue suministrado
        if not summoner_name and self.lcu.session:
            sum_info = self.lcu.request("GET", f"/lol-summoner/v1/summoners/by-puuid/{puuid}")
            if sum_info:
                summoner_name = sum_info.get("gameName") or sum_info.get("displayName", "Invocador")
                tag = sum_info.get("tagLine", "")
                if tag:
                    summoner_name = f"{summoner_name}#{tag}"
        
        name_display = summoner_name or "Aliado"

        # 2. Obtener Rango SoloQ y Flex
        rank_info = {
            "tier": "UNRANKED",
            "division": "",
            "lp": 0,
            "wins": 0,
            "losses": 0,
            "winrate": 0.0
        }

        ranked_data = self.lcu.request("GET", f"/lol-ranked/v1/ranked-stats/{puuid}")
        if ranked_data:
            soloq = ranked_data.get("queueMap", {}).get("RANKED_SOLO_5x5", {})
            tier = soloq.get("tier", "UNRANKED")
            if tier and tier != "UNRANKED":
                w = soloq.get("wins", 0)
                l = soloq.get("losses", 0)
                total = w + l
                wr = round((w / total * 100), 1) if total > 0 else 0.0
                rank_info = {
                    "tier": tier,
                    "division": soloq.get("division", ""),
                    "lp": soloq.get("leaguePoints", 0),
                    "wins": w,
                    "losses": l,
                    "winrate": wr
                }

        # 3. Obtener Historial de Partidas Recientes (Match History)
        matches_data = self.lcu.request("GET", f"/lol-match-history/v1/products/lol/{puuid}/matches")
        recent_games = []
        if matches_data:
            games_list = matches_data.get("games", {}).get("games", [])
            for g in games_list[:15]:
                # En LCU match history, participants[0] corresponde al jugador consultado
                participants = g.get("participants", [])
                if not participants:
                    continue
                p = participants[0]
                stats = p.get("stats", {})
                champ_id = p.get("championId", 0)
                champ_name = self.lcu.get_champion_name(champ_id) or f"Champ {champ_id}"
                
                recent_games.append({
                    "win": stats.get("win", False),
                    "kills": stats.get("kills", 0),
                    "deaths": stats.get("deaths", 0),
                    "assists": stats.get("assists", 0),
                    "champion_name": champ_name,
                    "champion_id": champ_id,
                    "role": p.get("timeline", {}).get("lane", "").lower()
                })

        # 4. Calcular Métricas Avanzadas (Racha, KDA promedio, Badges)
        streak_count = 0
        streak_type = None  # 'W' o 'L'
        badges = []

        if recent_games:
            # Calcular racha actual
            first_result = recent_games[0]["win"]
            streak_type = "W" if first_result else "L"
            for g in recent_games:
                if g["win"] == first_result:
                    streak_count += 1
                else:
                    break

            # Calcular Winrate reciente (últimas 10)
            sample = recent_games[:10]
            wins_count = sum(1 for g in sample if g["win"])
            recent_wr = round((wins_count / len(sample)) * 100, 1)

            # Promedios de KDA
            avg_kills = sum(g["kills"] for g in sample) / len(sample)
            avg_deaths = sum(g["deaths"] for g in sample) / len(sample)
            avg_assists = sum(g["assists"] for g in sample) / len(sample)
            kda_ratio = round((avg_kills + avg_assists) / max(1, avg_deaths), 2)

            # Campeones más jugados en el sample
            champ_counts: Dict[str, Dict[str, Any]] = {}
            for g in sample:
                cname = g["champion_name"]
                if cname not in champ_counts:
                    champ_counts[cname] = {"games": 0, "wins": 0}
                champ_counts[cname]["games"] += 1
                if g["win"]:
                    champ_counts[cname]["wins"] += 1

            top_champs = sorted(champ_counts.items(), key=lambda x: x[1]["games"], reverse=True)[:3]
            top_champs_formatted = []
            for cname, cdata in top_champs:
                c_wr = round((cdata["wins"] / cdata["games"]) * 100, 1)
                top_champs_formatted.append(f"{cname} ({cdata['games']}P, {c_wr}% WR)")

            # Generar Badges estilo Porofessor
            if streak_type == "W" and streak_count >= 3:
                badges.append(f"[!] EN RACHA (+{streak_count} Victorias)")
            elif streak_type == "L" and streak_count >= 3:
                badges.append(f"[!] TILT WARNING (-{streak_count} Derrotas)")

            if recent_wr >= 70.0:
                badges.append(f"[!] ALTO WINRATE ({recent_wr}% ultimas {len(sample)})")
            elif recent_wr <= 30.0:
                badges.append(f"[!] RACHA BAJA ({recent_wr}% ultimas {len(sample)})")

            if kda_ratio >= 3.0:
                badges.append(f"[+] KDA SOLIDO ({kda_ratio}:1)")
            elif avg_deaths >= 8.0:
                badges.append(f"[-] MUERE MUCHO ({avg_deaths:.1f} D/P)")
        else:
            recent_wr = 0.0
            kda_ratio = 0.0
            top_champs_formatted = []

        return {
            "name": name_display,
            "puuid": puuid,
            "assigned_position": assigned_position,
            "rank": rank_info,
            "recent_wr": recent_wr,
            "streak": f"+{streak_count} W" if streak_type == "W" else f"-{streak_count} L",
            "kda_ratio": kda_ratio,
            "top_champions": top_champs_formatted,
            "badges": badges
        }

    def _resolve_in_game_roster(self, my_puuid: Optional[str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[int]]:
        """
        Extrae la lista de los 10 jugadores en Pantalla de Carga / En Partida utilizando
        una arquitectura en cascada de 3 capas:
        1. Riot Live Client Data API (puerto local 2999) - Infalible en pantalla de carga e in-game.
        2. LCU API (/lol-gameflow/v1/session -> teamOne/teamTwo o playerChampionSelections).
        3. Riot Spectator API v5 (nube oficial de Riot, si se configuró una API Key).
        """
        allies: List[Dict[str, Any]] = []
        enemies: List[Dict[str, Any]] = []
        game_id: Optional[int] = None

        # -------------------------------------------------------------
        # CAPA 1: Live Client Data API (https://127.0.0.1:2999)
        # -------------------------------------------------------------
        try:
            res_live = self._live_session.get("https://127.0.0.1:2999/liveclientdata/playerlist", timeout=0.8)
            if res_live.status_code == 200:
                raw_players = res_live.json()
                if isinstance(raw_players, list) and len(raw_players) > 0:
                    my_name = ""
                    try:
                        res_name = self._live_session.get("https://127.0.0.1:2999/liveclientdata/activeplayername", timeout=0.5)
                        if res_name.status_code == 200:
                            my_name = res_name.text.replace('"', '').strip()
                    except Exception:
                        pass

                    my_team = "ORDER"
                    for p in raw_players:
                        p_name = p.get("summonerName", "")
                        if my_name and (p_name == my_name or my_name in p_name):
                            my_team = p.get("team", "ORDER")
                            break

                    print(f"[*] Live Client Data (2999) detectó {len(raw_players)} jugadores. Mi equipo: {my_team}")

                    for p in raw_players:
                        p_name = p.get("summonerName", "Invocador")
                        champ_name = p.get("championName", "")
                        pos = str(p.get("position", "")).lower()
                        if pos == "utility":
                            pos = "support"
                        is_me = bool(my_name and (p_name == my_name or my_name in p_name))
                        is_ally = (p.get("team") == my_team)

                        p_puuid = my_puuid if (is_me and my_puuid) else ""
                        if not p_puuid and self.lcu.session:
                            try:
                                clean_name = p_name.split("#")[0]
                                sum_res = self.lcu.request("GET", f"/lol-summoner/v1/summoners?name={p_name}")
                                if not sum_res:
                                    sum_res = self.lcu.request("GET", f"/lol-summoner/v1/summoners?name={clean_name}")
                                if sum_res and sum_res.get("puuid"):
                                    p_puuid = sum_res.get("puuid")
                            except Exception:
                                pass

                        if p_puuid:
                            profile = self.scout_puuid(p_puuid, summoner_name=p_name, assigned_position=pos)
                        else:
                            profile = {
                                "name": p_name,
                                "puuid": "",
                                "assigned_position": pos,
                                "rank": {"tier": "UNRANKED", "division": "", "lp": 0, "winrate": 0.0},
                                "recent_wr": 0.0,
                                "streak": "N/A",
                                "kda_ratio": 0.0,
                                "top_champions": [],
                                "badges": []
                            }

                        profile["champion_name"] = champ_name
                        profile["is_me"] = is_me

                        if is_ally:
                            allies.append(profile)
                        else:
                            enemies.append(profile)

                    if allies:
                        return allies, enemies, 999999
        except Exception:
            pass

        # -------------------------------------------------------------
        # CAPA 2: LCU /lol-gameflow/v1/session
        # -------------------------------------------------------------
        gameflow = self.lcu.request("GET", "/lol-gameflow/v1/session")
        if gameflow and gameflow.get("phase") in ("InProgress", "GameStart", "Reconnect"):
            game_data = gameflow.get("gameData", {})
            game_id = game_data.get("gameId")
            team_one = game_data.get("teamOne", [])
            team_two = game_data.get("teamTwo", [])

            # Si teamOne o teamTwo tienen jugadores
            if team_one or team_two:
                my_team_list = team_one
                enemy_team_list = team_two
                if any(p.get("puuid") == my_puuid for p in team_two):
                    my_team_list = team_two
                    enemy_team_list = team_one

                def process_lcu_team(plist: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
                    res = []
                    for p in plist:
                        p_puuid = p.get("puuid")
                        champ_id = p.get("championId", 0)
                        champ_name = self.lcu.get_champion_name(champ_id) or f"Champ {champ_id}"
                        role = p.get("selectedPosition", "").lower()
                        if role == "utility":
                            role = "support"
                        name = p.get("summonerName") or p.get("gameName") or "Invocador"
                        tag = p.get("tagLine", "")
                        if tag and "#" not in name:
                            name = f"{name}#{tag}"
                        is_me = (p_puuid == my_puuid) if my_puuid else False
                        if p_puuid:
                            prof = self.scout_puuid(p_puuid, summoner_name=name, assigned_position=role)
                        else:
                            prof = {
                                "name": name,
                                "puuid": "",
                                "assigned_position": role,
                                "rank": {"tier": "UNRANKED", "division": "", "lp": 0, "winrate": 0.0},
                                "recent_wr": 0.0,
                                "streak": "N/A",
                                "kda_ratio": 0.0,
                                "top_champions": [],
                                "badges": []
                            }
                        prof["champion_name"] = champ_name
                        prof["champion_id"] = champ_id
                        prof["is_me"] = is_me
                        res.append(prof)
                    return res

                allies = process_lcu_team(my_team_list)
                enemies = process_lcu_team(enemy_team_list)
                if allies:
                    return allies, enemies, game_id

            # Fallback 2.1: playerChampionSelections
            selections = game_data.get("playerChampionSelections", [])
            if selections:
                for idx, sel in enumerate(selections):
                    p_puuid = sel.get("puuid", "")
                    cid = sel.get("championId", 0)
                    cname = self.lcu.get_champion_name(cid) or f"Champ {cid}"
                    role = sel.get("selectedPosition", "").lower()
                    if role == "utility":
                        role = "support"
                    name = sel.get("summonerInternalName", f"Invocador {idx+1}")
                    is_me = (p_puuid == my_puuid) if my_puuid else False
                    if p_puuid:
                        prof = self.scout_puuid(p_puuid, summoner_name=name, assigned_position=role)
                    else:
                        prof = {
                            "name": name,
                            "puuid": "",
                            "assigned_position": role,
                            "rank": {"tier": "UNRANKED", "division": "", "lp": 0, "winrate": 0.0},
                            "recent_wr": 0.0,
                            "streak": "N/A",
                            "kda_ratio": 0.0,
                            "top_champions": [],
                            "badges": []
                        }
                    prof["champion_name"] = cname
                    prof["is_me"] = is_me
                    if idx < 5:
                        allies.append(prof)
                    else:
                        enemies.append(prof)
                if allies:
                    return allies, enemies, game_id

        # -------------------------------------------------------------
        # CAPA 3: Riot Spectator API v5 (Cloud API)
        # -------------------------------------------------------------
        if self.riot_api and my_puuid:
            try:
                spec = self.riot_api.get_active_game_by_puuid(my_puuid)
                if spec and "participants" in spec:
                    parts = spec.get("participants", [])
                    my_participant = next((p for p in parts if p.get("puuid") == my_puuid), None)
                    my_team_id = my_participant.get("teamId", 100) if my_participant else 100

                    for p in parts:
                        p_puuid = p.get("puuid", "")
                        cid = p.get("championId", 0)
                        cname = self.lcu.get_champion_name(cid) or f"Champ {cid}"
                        r_name = p.get("riotId", "") or p.get("summonerName", "Invocador")
                        is_me = (p_puuid == my_puuid)
                        is_ally = (p.get("teamId") == my_team_id)

                        if p_puuid:
                            prof = self.scout_puuid(p_puuid, summoner_name=r_name)
                        else:
                            prof = {
                                "name": r_name,
                                "puuid": "",
                                "assigned_position": "",
                                "rank": {"tier": "UNRANKED", "division": "", "lp": 0, "winrate": 0.0},
                                "recent_wr": 0.0,
                                "streak": "N/A",
                                "kda_ratio": 0.0,
                                "top_champions": [],
                                "badges": []
                            }
                        prof["champion_name"] = cname
                        prof["is_me"] = is_me

                        if is_ally:
                            allies.append(prof)
                        else:
                            enemies.append(prof)

                    if allies:
                        return allies, enemies, spec.get("gameId", 999998)
            except Exception as e:
                print(f"[!] Error consultando Spectator API: {e}")

        return allies, enemies, game_id

    def scout_active_match(self, force: bool = False) -> Dict[str, Any]:
        """
        Escanea la partida activa de forma inteligente:
        1. Si está en Pantalla de Carga o En Partida (InProgress):
           Revela a los 10 jugadores (5 Aliados y 5 Rivales) sin censura ni anonimato
           usando Live Client Data (2999), LCU o Spectator API.
        2. Si está en Selección de Campeones (ChampSelect):
           Si no es anónimo, muestra los aliados; si es SoloQ, indica que se revelarán en pantalla de carga.
        """
        if not self.lcu.session or not self.lcu.port:
            if not self.lcu.connect():
                return {"status": "disconnected", "message": "Cliente LoL no detectado"}

        me_info = self.lcu.get_current_summoner()
        my_puuid = me_info.get("puuid") if me_info else None

        # 1. Comprobar si está en Pantalla de Carga o En Partida mediante la cascada de 3 capas
        allies, enemies, game_id = self._resolve_in_game_roster(my_puuid)

        if allies:
            # Evitar re-analizar la misma partida en bucle si ya fue escaneada
            if not force and game_id and game_id == self._cached_game_id and self._cached_game_data is not None:
                return self._cached_game_data

            print(f"[*] Partida activa confirmada con {len(allies)} aliados y {len(enemies)} rivales. Generando análisis...")

            # Buscar enfrentamiento directo en línea (Matchup de carril)
            direct_matchup = None
            my_player = next((p for p in allies if p.get("is_me")), None)
            if my_player:
                my_champ = my_player.get("champion_name")
                my_pos = my_player.get("assigned_position", "").lower()
                
                # Buscar al rival en la misma posición
                enemy_match = next((e for e in enemies if e.get("assigned_position", "").lower() == my_pos and my_pos), None)
                if enemy_match and my_champ:
                    enemy_champ = enemy_match.get("champion_name")
                    try:
                        direct_matchup = self.lolalytics.get_matchup_analysis(my_champ, enemy_champ, my_pos)
                    except Exception:
                        pass

            # Calcular balance competitivo y predicción de victoria de la partida
            team_balance = self.calculate_team_balance(allies, enemies)

            result = {
                "status": "in_game",
                "phase_name": "En Partida / Pantalla de Carga",
                "allies": allies,
                "enemies": enemies,
                "direct_matchup": direct_matchup,
                "team_balance": team_balance
            }

            # Guardar en caché únicamente cuando tenemos datos válidos
            self._cached_game_id = game_id
            self._cached_game_data = result
            return result

        # 2. Comprobar si está en Selección de Campeones (ChampSelect)
        # Si salimos de partida, limpiar la caché de partida previa
        self._cached_game_id = None
        self._cached_game_data = None
        session = self.lcu.get_champ_select_session()
        if session:
            my_cell_id = session.get("localPlayerCellId")
            my_team = session.get("myTeam", [])
            allies = []
            has_anonymous = False

            for p in my_team:
                cell_id = p.get("cellId")
                is_me = (cell_id == my_cell_id)
                role = p.get("assignedPosition", "all").lower()
                if role == "utility":
                    role = "support"
                puuid = p.get("puuid")

                if not puuid or len(puuid) < 5:
                    has_anonymous = True
                    alias = f"Aliado {cell_id + 1}" if not is_me else "TU (Tu cuenta)"
                    allies.append({
                        "name": alias,
                        "is_me": is_me,
                        "assigned_position": role,
                        "champion_name": self.lcu.get_champion_name(p.get("championId") or p.get("championPickIntent", 0)) or "Eligiendo...",
                        "rank": {"tier": "ANONIMO", "division": "", "lp": 0, "winrate": 0.0},
                        "recent_wr": 0.0,
                        "streak": "En Draft",
                        "kda_ratio": 0.0,
                        "top_champions": [],
                        "badges": ["[i] SoloQ Draft Anonimo"]
                    })
                else:
                    profile = self.scout_puuid(puuid, assigned_position=role)
                    profile["champion_name"] = self.lcu.get_champion_name(p.get("championId") or p.get("championPickIntent", 0)) or "Eligiendo..."
                    profile["is_me"] = is_me
                    allies.append(profile)

            # Detectar picks del equipo rival en selección de campeones
            enemy_picks = []
            their_team = session.get("theirTeam", [])
            for p in their_team:
                cid = p.get("championId", 0)
                if cid > 0:
                    cname = self.lcu.get_champion_name(cid)
                    if cname and cname not in enemy_picks:
                        enemy_picks.append(cname)

            # También revisar acciones completadas de pick del equipo rival
            for action_group in session.get("actions", []):
                for act in action_group:
                    if act.get("type") == "pick" and act.get("completed") and not act.get("isAllyAction"):
                        cid = act.get("championId", 0)
                        if cid > 0:
                            cname = self.lcu.get_champion_name(cid)
                            if cname and cname not in enemy_picks:
                                enemy_picks.append(cname)

            # Determinar matchup o recomendaciones de counter si hay campeón propio o rival
            direct_matchup = None
            counter_suggestions = None
            my_player = next((p for p in allies if p.get("is_me")), None)

            if my_player:
                my_champ = my_player.get("champion_name")
                my_role = my_player.get("assigned_position", "").lower()

                # Si ambos tienen campeon definido
                if my_champ and my_champ not in ("Eligiendo...", "Desconocido") and enemy_picks:
                    try:
                        # Comparar contra el pick enemigo principal
                        direct_matchup = self.lolalytics.get_matchup_analysis(my_champ, enemy_picks[0], my_role or None)
                    except Exception:
                        pass
                elif enemy_picks and (not my_champ or my_champ in ("Eligiendo...", "Desconocido")):
                    # El rival ya eligió pero tú aún no: Sugerir counters para elegir
                    try:
                        counters_data = self.lolalytics.get_champion_counters(enemy_picks[0], my_role or None)
                        counter_suggestions = {
                            "enemy_champion": enemy_picks[0],
                            "counters": counters_data.get("worst", [])  # Los que vencen al enemigo
                        }
                    except Exception:
                        pass

            return {
                "status": "champ_select",
                "phase_name": "Selección de Campeones",
                "has_anonymous": has_anonymous,
                "allies": allies,
                "enemies": [{"name": "Rival", "champion_name": c, "rank": {"tier": "ANONIMO", "division": "", "lp": 0, "winrate": 0.0}, "streak": "Draft", "top_champions": [], "badges": []} for c in enemy_picks],
                "direct_matchup": direct_matchup,
                "counter_suggestions": counter_suggestions
            }

        # 3. No está ni en selección ni en partida
        return {
            "status": "idle",
            "phase_name": "Esperando partida",
            "allies": [],
            "enemies": []
        }

    def calculate_team_balance(self, allies: List[Dict[str, Any]], enemies: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Calcula el balance competitivo y predicción de victoria entre ambos equipos:
        - Probabilidad de victoria estimada (% Aliados vs % Enemigos)
        - Winrate promedio y rango medio por bando
        - Perfil y balance de daño (AD, AP, Tanque) con alertas tácticas
        - Identificación de MVP Aliado, Mayor Amenaza Rival y Objetivo Vulnerable
        - Veredicto estratégico de partida
        """
        if not allies or not enemies or len(allies) < 1 or len(enemies) < 1:
            return None

        AP_CHAMPIONS = {
            "ahri", "akali", "anivia", "annie", "aurelionsol", "azir", "bard", "brand", 
            "cassiopeia", "chogath", "diana", "ekko", "elise", "evelynn", "fiddlesticks", 
            "fizz", "galio", "gragas", "gwen", "heimerdinger", "hwei", "ivern", "janna", 
            "karma", "karthus", "kassadin", "katarina", "kayle", "kennen", "leblanc", 
            "lissandra", "lillia", "lux", "malzahar", "milio", "mordekaiser", "morgana", 
            "nami", "neeko", "nidalee", "nunu", "orianna", "renataglasc", "ryze", "seraphine", 
            "singed", "sona", "soraka", "swain", "sylas", "syndra", "taliyah", "teemo", 
            "twistedfate", "veigar", "velkoz", "vex", "viktor", "vladimir", "xerath", 
            "yuumi", "ziggs", "zoe", "zyra"
        }

        TANK_CHAMPIONS = {
            "alistar", "amumu", "braum", "drmundo", "ksante", "leona", "malphite", 
            "maokai", "nautilus", "ornn", "poppy", "rammus", "rell", "sejuani", 
            "shen", "sion", "skarner", "tahmkench", "taric", "thresh", "zac"
        }

        TIER_SCORES = {
            "IRON": 15, "BRONZE": 25, "SILVER": 35, "GOLD": 48,
            "PLATINUM": 60, "EMERALD": 72, "DIAMOND": 85,
            "MASTER": 95, "GRANDMASTER": 100, "CHALLENGER": 105, "UNRANKED": 50
        }

        def score_to_tier_label(score: float) -> str:
            if score >= 101: return "Challenger"
            if score >= 96: return "Grandmaster"
            if score >= 88: return "Master"
            if score >= 78: return "Diamond"
            if score >= 65: return "Emerald"
            if score >= 53: return "Platinum"
            if score >= 40: return "Gold"
            if score >= 30: return "Silver"
            if score >= 20: return "Bronze"
            return "Iron"

        def clean_champ_name(name: str) -> str:
            return (name or "").lower().replace("'", "").replace(" ", "").replace(".", "").replace("&", "")

        def calc_damage_profile(team_players: List[Dict[str, Any]]) -> Dict[str, Any]:
            ad = 0
            ap = 0
            tank = 0
            total = len(team_players)
            if total == 0:
                return {"ad_pct": 50, "ap_pct": 50, "tank_pct": 0, "summary": "N/A", "alert": None}

            for p in team_players:
                c_name = clean_champ_name(p.get("champion_name", ""))
                if c_name in TANK_CHAMPIONS:
                    tank += 1
                elif c_name in AP_CHAMPIONS:
                    ap += 1
                else:
                    ad += 1

            ad_pct = int(round((ad / total) * 100))
            ap_pct = int(round((ap / total) * 100))
            tank_pct = int(round((tank / total) * 100))

            alert = None
            if ad_pct >= 75:
                summary = "Casi Full Físico (AD)"
                alert = "⚠️ Composición ~80% AD: Compra Botas Blindadas (Tabis) y Armadura temprano."
            elif ap_pct >= 75:
                summary = "Casi Full Mágico (AP)"
                alert = "⚠️ Composición ~80% AP: Compra Botas de Mercurio y Resistencia Mágica temprano."
            elif tank_pct >= 40:
                summary = "Alta Presencia de Tanques"
                alert = "🛡️ Rival con alta Frontline: Prepara penetración (Lord Dominik / Vacío / Liandry)."
            else:
                summary = "Balance Mixto Equilibrado"

            return {
                "ad_pct": ad_pct,
                "ap_pct": ap_pct,
                "tank_pct": tank_pct,
                "summary": summary,
                "alert": alert
            }

        def evaluate_player(p: Dict[str, Any]) -> Dict[str, Any]:
            rank_data = p.get("rank", {})
            tier_str = str(rank_data.get("tier", "UNRANKED")).upper()
            tier_base = TIER_SCORES.get(tier_str, 50.0)

            # Winrate (preferir SoloQ rank wr, o recent_wr)
            wr = rank_data.get("winrate") or p.get("recent_wr") or 50.0
            if wr == 0:
                wr = 50.0
            wr_impact = (wr - 50.0) * 0.9

            # Racha
            streak = str(p.get("streak", ""))
            streak_impact = 0.0
            is_win_streak = False
            is_loss_streak = False

            if "W" in streak:
                is_win_streak = True
                try:
                    num = int(streak.replace("W", "").strip())
                    streak_impact = min(num * 2.5, 9.0)
                except Exception:
                    streak_impact = 2.5
            elif "L" in streak:
                is_loss_streak = True
                try:
                    num = int(streak.replace("L", "").strip())
                    streak_impact = -min(num * 3.0, 11.0)
                except Exception:
                    streak_impact = -3.0

            # KDA
            kda = float(p.get("kda_ratio", 2.0) or 2.0)
            kda_impact = min(max((kda - 2.0) * 1.6, -5.0), 5.0)

            # Badges (OTP / Main / Tilt)
            badges = p.get("badges", [])
            badge_impact = 0.0
            for b in badges:
                b_low = str(b).lower()
                if "otp" in b_low or "main" in b_low:
                    badge_impact += 3.5
                elif "tilt" in b_low or "derrotas" in b_low:
                    badge_impact -= 3.5

            total_score = max(10.0, tier_base + wr_impact + streak_impact + kda_impact + badge_impact)

            return {
                "player": p,
                "score": total_score,
                "tier_base": tier_base,
                "wr": wr,
                "kda": kda,
                "is_win_streak": is_win_streak,
                "is_loss_streak": is_loss_streak
            }

        evaluated_allies = [evaluate_player(p) for p in allies]
        evaluated_enemies = [evaluate_player(p) for p in enemies]

        # Métricas Colectivas
        avg_ally_wr = round(sum(ep["wr"] for ep in evaluated_allies) / len(evaluated_allies), 1)
        avg_enemy_wr = round(sum(ep["wr"] for ep in evaluated_enemies) / len(evaluated_enemies), 1)

        avg_ally_kda = round(sum(ep["kda"] for ep in evaluated_allies) / len(evaluated_allies), 1)
        avg_enemy_kda = round(sum(ep["kda"] for ep in evaluated_enemies) / len(evaluated_enemies), 1)

        avg_ally_tier_score = sum(ep["tier_base"] for ep in evaluated_allies) / len(evaluated_allies)
        avg_enemy_tier_score = sum(ep["tier_base"] for ep in evaluated_enemies) / len(evaluated_enemies)

        ally_win_streaks = sum(1 for ep in evaluated_allies if ep["is_win_streak"])
        ally_loss_streaks = sum(1 for ep in evaluated_allies if ep["is_loss_streak"])
        enemy_win_streaks = sum(1 for ep in evaluated_enemies if ep["is_win_streak"])
        enemy_loss_streaks = sum(1 for ep in evaluated_enemies if ep["is_loss_streak"])

        # Puntuación global y probabilidad de victoria
        ally_total_score = sum(ep["score"] for ep in evaluated_allies) / len(evaluated_allies)
        enemy_total_score = sum(ep["score"] for ep in evaluated_enemies) / len(evaluated_enemies)

        diff = ally_total_score - enemy_total_score
        # Proyectar a probabilidad suave (rango competitivo 34% a 66%)
        prob_delta = max(-16.0, min(16.0, diff * 0.75))
        ally_prob = round(50.0 + prob_delta, 1)
        enemy_prob = round(100.0 - ally_prob, 1)

        # Determinar Veredicto Táctico
        if ally_prob >= 56.0:
            verdict_title = f"🌟 Gran Ventaja para Tu Equipo (+{round(ally_prob - 50.0, 1)}%)"
            verdict_desc = f"Tu escuadra supera al rival en consistencia (Winrate medio {avg_ally_wr}% vs {avg_enemy_wr}%) y cuenta con mejor inercia competitiva."
            verdict_type = "ally_dominant"
        elif ally_prob >= 51.5:
            verdict_title = f"🔵 Ligera Ventaja para Tu Equipo (+{round(ally_prob - 50.0, 1)}%)"
            verdict_desc = f"Matchup favorable en estadísticas individuales. Mantén la calma en juego temprano y asegura objetivos."
            verdict_type = "ally_favored"
        elif 48.5 <= ally_prob < 51.5:
            verdict_title = "⚖️ Partida Altamente Equilibrada (50 / 50)"
            verdict_desc = "Fuerzas muy parejas entre ambas escuadras. La partida se definirá por la toma del Dragón/Heraldo y escaramuzas de equipo."
            verdict_type = "balanced"
        elif ally_prob <= 44.0:
            verdict_title = f"🔴 Ventaja Estadística para el Rival (+{round(enemy_prob - 50.0, 1)}%)"
            verdict_desc = f"El equipo enemigo cuenta con mayor racha o MMR promedio ({avg_enemy_wr}% WR rival). Juega agrupado y castiga sus sobreextensiones."
            verdict_type = "enemy_dominant"
        else:
            verdict_title = f"🟡 Ligera Ventaja Rival (+{round(enemy_prob - 50.0, 1)}%)"
            verdict_desc = "El rival presenta un rendimiento ligeramente superior. Evita peleas innecesarias antes de alcanzar los picos de objetos."
            verdict_type = "enemy_favored"

        # Identificar Jugadores Clave
        # 1. MVP Aliado (Mayor puntaje aliado)
        best_ally = max(evaluated_allies, key=lambda x: x["score"])
        ally_mvp_data = {
            "name": best_ally["player"].get("name", "Aliado"),
            "champion": best_ally["player"].get("champion_name", "Campeón"),
            "role": best_ally["player"].get("assigned_position", "").upper() or "LANE",
            "reason": f"{best_ally['wr']}% WR | KDA {best_ally['kda']}:1 | {best_ally['player'].get('streak', 'Estable')}"
        }

        # 2. Mayor Amenaza Rival (Mayor puntaje rival)
        best_enemy = max(evaluated_enemies, key=lambda x: x["score"])
        enemy_threat_data = {
            "name": best_enemy["player"].get("name", "Rival"),
            "champion": best_enemy["player"].get("champion_name", "Campeón"),
            "role": best_enemy["player"].get("assigned_position", "").upper() or "LANE",
            "reason": f"{best_enemy['wr']}% WR | KDA {best_enemy['kda']}:1 | {best_enemy['player'].get('streak', 'Peligro')}"
        }

        # 3. Objetivo Vulnerable / Eslabón Débil (Menor puntaje rival)
        weakest_enemy = min(evaluated_enemies, key=lambda x: x["score"])
        enemy_weak_data = {
            "name": weakest_enemy["player"].get("name", "Rival"),
            "champion": weakest_enemy["player"].get("champion_name", "Campeón"),
            "role": weakest_enemy["player"].get("assigned_position", "").upper() or "LANE",
            "reason": f"{weakest_enemy['wr']}% WR | {weakest_enemy['player'].get('streak', 'Bajo rendimiento')}"
        }

        # Perfiles de Daño
        ally_damage = calc_damage_profile(allies)
        enemy_damage = calc_damage_profile(enemies)

        return {
            "ally_win_prob": ally_prob,
            "enemy_win_prob": enemy_prob,
            "verdict_title": verdict_title,
            "verdict_desc": verdict_desc,
            "verdict_type": verdict_type,
            "allies_stats": {
                "avg_winrate": avg_ally_wr,
                "avg_tier": score_to_tier_label(avg_ally_tier_score),
                "avg_kda": avg_ally_kda,
                "streaks_win": ally_win_streaks,
                "streaks_loss": ally_loss_streaks,
                "damage_profile": ally_damage
            },
            "enemies_stats": {
                "avg_winrate": avg_enemy_wr,
                "avg_tier": score_to_tier_label(avg_enemy_tier_score),
                "avg_kda": avg_enemy_kda,
                "streaks_win": enemy_win_streaks,
                "streaks_loss": enemy_loss_streaks,
                "damage_profile": enemy_damage
            },
            "key_players": {
                "ally_mvp": ally_mvp_data,
                "enemy_threat": enemy_threat_data,
                "enemy_weak_link": enemy_weak_data
            }
        }

    def scout_current_lobby(self) -> List[Dict[str, Any]]:
        """
        Escanea la selección de campeones actual y analiza a los 4 compañeros de equipo.
        """
        data = self.scout_active_match()
        return data.get("allies", [])

if __name__ == "__main__":
    api_key_test = "RGAPI-1330dbb6-a728-48e2-819a-b449474b45bb"
    scout = ScoutService(riot_api_key=api_key_test)
    
    # Prueba rapida: Si el cliente de LoL esta abierto, hacer scouting de tu propio perfil
    if scout.lcu.connect():
        me = scout.lcu.get_current_summoner()
        if me:
            my_puuid = me.get("puuid")
            print(f"[*] Probando modulo de Scouting con tu cuenta activa...")
            res = scout.scout_puuid(my_puuid, summoner_name=f"{me.get('gameName')}#{me.get('tagLine')}", assigned_position="middle")
            print(f"\n[+] Perfil analizado exitosamente:")
            print(f"    Invocador: {res['name']}")
            print(f"    Rango SoloQ: {res['rank']['tier']} {res['rank']['division']} ({res['rank']['lp']} LP) - {res['rank']['winrate']}% WR")
            print(f"    Racha actual: {res['streak']}")
            print(f"    Winrate reciente: {res['recent_wr']}% (ultimas 10)")
            print(f"    KDA Ratio: {res['kda_ratio']}:1")
            print(f"    Champs frecuentes: {', '.join(res['top_champions'])}")
            print(f"    Etiquetas: {' '.join(res['badges'])}")
