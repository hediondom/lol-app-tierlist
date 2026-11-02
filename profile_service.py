import os
import sys
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from lcu_connector import LCUConnector
from ddragon import get_ddragon

QUEUE_NAMES = {
    420: "Ranked Solo/Duo",
    440: "Ranked Flex",
    400: "Normal Draft",
    430: "Normal Oculta",
    450: "ARAM",
    1700: "Arena (2v2v2v2)",
    1900: "URF",
    830: "Co-op vs IA",
    840: "Co-op vs IA",
    850: "Co-op vs IA"
}

SPELL_NAMES = {
    1: "SummonerBoost",     # Limpiar
    3: "SummonerExhaust",   # Extenuación
    4: "SummonerFlash",     # Flash
    6: "SummonerHaste",     # Fantasma
    7: "SummonerHeal",      # Curación
    11: "SummonerSmite",    # Castigo
    12: "SummonerTeleport", # Teleport
    14: "SummonerDot",      # Prender
    21: "SummonerBarrier",  # Barrera
    32: "SummonerSnowball"  # Bola de nieve
}

ROLE_NAMES = {
    "top": "TOP",
    "jungle": "JUNGLE",
    "middle": "MID",
    "mid": "MID",
    "bottom": "ADC",
    "utility": "SUPPORT",
    "support": "SUPPORT"
}

class ProfileService:
    """
    Servicio de Perfil del Invocador e Historial de Partidas
    estilo OP.GG / Porofessor.
    """
    def __init__(self, lcu_connector: Optional[LCUConnector] = None):
        self.lcu = lcu_connector or LCUConnector()

    @property
    def ddragon_version(self) -> str:
        """Versión de Data Dragon para los iconos (se actualiza sola en segundo plano)."""
        return get_ddragon().version

    def get_full_profile(self) -> Dict[str, Any]:
        """
        Obtiene el perfil completo del usuario actual conectado al cliente de LoL.
        Incluye rangos (SoloQ/Flex), campeones más jugados, resumen de rachas
        y el historial de las últimas 20 partidas detalladas al estilo OP.GG.
        """
        if not self.lcu.session or not self.lcu.port:
            if not self.lcu.connect():
                return {
                    "status": "disconnected",
                    "message": "Abre el cliente de League of Legends para cargar tu perfil e historial."
                }

        me = self.lcu.get_current_summoner()
        if not me or not me.get("puuid"):
            return {
                "status": "disconnected",
                "message": "Inicia sesión en League of Legends para ver tu perfil."
            }

        puuid = me["puuid"]
        game_name = me.get("gameName") or me.get("displayName", "Invocador")
        tag_line = me.get("tagLine", "")
        full_name = f"{game_name}#{tag_line}" if tag_line else game_name
        summoner_level = me.get("summonerLevel", 1)
        profile_icon_id = me.get("profileIconId", 29)

        # 1. Rango SoloQ y Flex
        ranked_info = {
            "soloq": {
                "tier": "UNRANKED",
                "division": "",
                "lp": 0,
                "wins": 0,
                "losses": 0,
                "winrate": 0.0
            },
            "flex": {
                "tier": "UNRANKED",
                "division": "",
                "lp": 0,
                "wins": 0,
                "losses": 0,
                "winrate": 0.0
            }
        }

        ranked_data = self.lcu.request("GET", f"/lol-ranked/v1/ranked-stats/{puuid}")
        if ranked_data:
            q_map = ranked_data.get("queueMap", {})
            solo = q_map.get("RANKED_SOLO_5x5")
            if solo and solo.get("tier") and solo.get("tier") != "UNRANKED":
                w = solo.get("wins", 0)
                l = solo.get("losses", 0)
                tot = w + l
                ranked_info["soloq"] = {
                    "tier": solo.get("tier", "UNRANKED"),
                    "division": solo.get("division", ""),
                    "lp": solo.get("leaguePoints", 0),
                    "wins": w,
                    "losses": l,
                    "winrate": round((w / tot) * 100, 1) if tot > 0 else 0.0
                }

            flex = q_map.get("RANKED_FLEX_SR")
            if flex and flex.get("tier") and flex.get("tier") != "UNRANKED":
                w = flex.get("wins", 0)
                l = flex.get("losses", 0)
                tot = w + l
                ranked_info["flex"] = {
                    "tier": flex.get("tier", "UNRANKED"),
                    "division": flex.get("division", ""),
                    "lp": flex.get("leaguePoints", 0),
                    "wins": w,
                    "losses": l,
                    "winrate": round((w / tot) * 100, 1) if tot > 0 else 0.0
                }

        # 2. Historial de Partidas Detallado (Match History)
        matches_endpoint = f"/lol-match-history/v1/products/lol/{puuid}/matches?begIndex=0&endIndex=20"
        mh_data = self.lcu.request("GET", matches_endpoint)
        games_list = mh_data.get("games", {}).get("games", []) if mh_data else []

        matches = []
        champ_stats: Dict[int, Dict[str, Any]] = {}
        role_counts = {"top": 0, "jungle": 0, "mid": 0, "adc": 0, "support": 0}

        now_ms = int(time.time() * 1000)

        for g in games_list:
            participants = g.get("participants", [])
            if not participants:
                continue

            # Buscar al participante local
            p_local = participants[0]
            for p in participants:
                # Comprobar si coincide con el puuid o participantId
                if p.get("puuid") == puuid:
                    p_local = p
                    break

            stats = p_local.get("stats", {})
            champ_id = p_local.get("championId", 0)
            champ_name = self.lcu.get_champion_name(champ_id) or f"Campeón {champ_id}"
            champ_slug = champ_name.lower().replace("'", "").replace(" ", "").replace(".", "")

            win = stats.get("win", False)
            kills = stats.get("kills", 0)
            deaths = stats.get("deaths", 0)
            assists = stats.get("assists", 0)
            kda_ratio = round((kills + assists) / max(1, deaths), 2)
            champ_level = stats.get("champLevel", 1)

            # CS y CS por minuto
            duration_sec = g.get("gameDuration", 0)
            duration_min = max(1, duration_sec / 60)
            minions = stats.get("totalMinionsKilled", 0) + stats.get("neutralMinionsKilled", 0)
            cs_per_min = round(minions / duration_min, 1)

            # Tiempo transcurrido
            creation_ms = g.get("gameCreation", now_ms)
            elapsed_sec = max(0, (now_ms - creation_ms) // 1000)
            if elapsed_sec < 3600:
                time_ago = f"Hace {max(1, elapsed_sec // 60)}m"
            elif elapsed_sec < 86400:
                time_ago = f"Hace {elapsed_sec // 3600}h"
            else:
                time_ago = f"Hace {elapsed_sec // 86400}d"

            mins = duration_sec // 60
            secs = duration_sec % 60
            duration_str = f"{mins}m {secs:02d}s"

            # Cola / Modo de juego
            queue_id = g.get("queueId", 0)
            queue_name = QUEUE_NAMES.get(queue_id, g.get("gameMode", "Clásica"))

            # Participación en Asesinatos (P/Kill %)
            team_id = p_local.get("teamId", 100)
            team_kills = sum(p.get("stats", {}).get("kills", 0) for p in participants if p.get("teamId") == team_id)
            kill_participation = round(((kills + assists) / max(1, team_kills)) * 100) if team_kills > 0 else 0

            # Objetos (0 a 6)
            items = [stats.get(f"item{i}", 0) for i in range(7)]

            # Hechizos de Invocador
            spell1_id = p_local.get("spell1Id", 4)
            spell2_id = p_local.get("spell2Id", 14)
            spell1_name = get_ddragon().spell_key_name(spell1_id) or SPELL_NAMES.get(spell1_id, "SummonerFlash")
            spell2_name = get_ddragon().spell_key_name(spell2_id) or SPELL_NAMES.get(spell2_id, "SummonerDot")

            # Rol jugado
            lane = str(p_local.get("timeline", {}).get("lane", "")).lower()
            role_mapped = ROLE_NAMES.get(lane, "")
            if role_mapped:
                key = role_mapped.lower()
                if key in role_counts:
                    role_counts[key] += 1

            # Participantes (10 Invocadores de la partida para el mini-grid)
            allies_list = []
            enemies_list = []
            identities = {id_obj.get("participantId"): id_obj.get("player", {}) for id_obj in g.get("participantIdentities", [])}

            for p in participants:
                p_c_id = p.get("championId", 0)
                p_c_name = self.lcu.get_champion_name(p_c_id) or f"Champ {p_c_id}"
                p_c_slug = p_c_name.lower().replace("'", "").replace(" ", "").replace(".", "")
                p_id = p.get("participantId")
                p_ident = identities.get(p_id, {})
                p_sum_name = p_ident.get("summonerName") or p_ident.get("gameName") or f"Invocador {p_id}"
                
                is_me_p = (p.get("puuid") == puuid or p_id == p_local.get("participantId"))
                player_entry = {
                    "champion_name": p_c_name,
                    "champion_slug": p_c_slug,
                    "name": p_sum_name,
                    "is_me": is_me_p
                }

                if p.get("teamId") == team_id:
                    allies_list.append(player_entry)
                else:
                    enemies_list.append(player_entry)

            matches.append({
                "game_id": g.get("gameId"),
                "win": win,
                "queue_name": queue_name,
                "time_ago": time_ago,
                "duration_str": duration_str,
                "champion_name": champ_name,
                "champion_slug": champ_slug,
                "champ_level": champ_level,
                "kills": kills,
                "deaths": deaths,
                "assists": assists,
                "kda_ratio": kda_ratio,
                "cs": minions,
                "cs_per_min": cs_per_min,
                "kill_participation": kill_participation,
                "items": items,
                "spell1_name": spell1_name,
                "spell2_name": spell2_name,
                "allies": allies_list,
                "enemies": enemies_list
            })

            # Acumular estadísticas por campeón
            if champ_id not in champ_stats:
                champ_stats[champ_id] = {
                    "champion_id": champ_id,
                    "champion_name": champ_name,
                    "champion_slug": champ_slug,
                    "games": 0,
                    "wins": 0,
                    "kills": 0,
                    "deaths": 0,
                    "assists": 0,
                    "cs": 0
                }
            cs_entry = champ_stats[champ_id]
            cs_entry["games"] += 1
            if win: cs_entry["wins"] += 1
            cs_entry["kills"] += kills
            cs_entry["deaths"] += deaths
            cs_entry["assists"] += assists
            cs_entry["cs"] += minions

        # 3. Resumen Global Reciente (Gráfico Donut y KDA total)
        total_games = len(matches)
        wins_count = sum(1 for m in matches if m["win"])
        losses_count = total_games - wins_count
        overall_wr = round((wins_count / total_games) * 100) if total_games > 0 else 0

        tot_k = sum(m["kills"] for m in matches)
        tot_d = sum(m["deaths"] for m in matches)
        tot_a = sum(m["assists"] for m in matches)
        avg_k = round(tot_k / max(1, total_games), 1)
        avg_d = round(tot_d / max(1, total_games), 1)
        avg_a = round(tot_a / max(1, total_games), 1)
        total_kda_ratio = round((tot_k + tot_a) / max(1, tot_d), 2)
        avg_kill_part = round(sum(m["kill_participation"] for m in matches) / max(1, total_games))

        # Campeones más jugados ordenados por número de partidas
        most_played = []
        for cid, data in sorted(champ_stats.items(), key=lambda x: x[1]["games"], reverse=True):
            g_count = data["games"]
            w_count = data["wins"]
            l_count = g_count - w_count
            c_wr = round((w_count / g_count) * 100)
            c_kda = round((data["kills"] + data["assists"]) / max(1, data["deaths"]), 2)
            c_cs_avg = round(data["cs"] / g_count, 1)

            most_played.append({
                "champion_id": cid,
                "champion_name": data["champion_name"],
                "champion_slug": data["champion_slug"],
                "games": g_count,
                "wins": w_count,
                "losses": l_count,
                "winrate": c_wr,
                "kda_ratio": c_kda,
                "avg_k": round(data["kills"] / g_count, 1),
                "avg_d": round(data["deaths"] / g_count, 1),
                "avg_a": round(data["assists"] / g_count, 1),
                "avg_cs": c_cs_avg
            })

        # Distribución de roles en porcentaje
        tot_roles = sum(role_counts.values()) or 1
        role_distribution = {
            "top": round((role_counts["top"] / tot_roles) * 100),
            "jungle": round((role_counts["jungle"] / tot_roles) * 100),
            "mid": round((role_counts["mid"] / tot_roles) * 100),
            "adc": round((role_counts["adc"] / tot_roles) * 100),
            "support": round((role_counts["support"] / tot_roles) * 100)
        }

        return {
            "status": "connected",
            "summoner": {
                "name": full_name,
                "game_name": game_name,
                "tag_line": tag_line,
                "level": summoner_level,
                "icon_id": profile_icon_id,
                "icon_url": f"https://ddragon.leagueoflegends.com/cdn/{self.ddragon_version}/img/profileicon/{profile_icon_id}.png"
            },
            "ranked": ranked_info,
            "recent_summary": {
                "total_games": total_games,
                "wins": wins_count,
                "losses": losses_count,
                "winrate": overall_wr,
                "avg_kills": avg_k,
                "avg_deaths": avg_d,
                "avg_assists": avg_a,
                "kda_ratio": total_kda_ratio,
                "kill_participation": avg_kill_part,
                "recent_champions": most_played[:3],
                "role_distribution": role_distribution
            },
            "most_played_champions": most_played,
            "matches": matches,
            "ddragon_version": self.ddragon_version
        }
