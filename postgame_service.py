import os
import sys
import time
from typing import Dict, Any, List, Optional
from lcu_connector import LCUConnector

class PostGameService:
    """
    Servicio de Análisis Post-Partida (Autopsia del Game).
    Evalúa la última partida jugada y asigna medallas de rendimiento:
    - ¿Qué hiciste bien? (Supervivencia, CS/min Master, Alto P/Kill)
    - ¿Qué te costó la partida? (Muertes excesivas, desconexión de peleas, déficit de farmeo)
    """
    def __init__(self, lcu_connector: Optional[LCUConnector] = None):
        self.lcu = lcu_connector or LCUConnector()
        self._last_analyzed_game_id: Optional[int] = None
        self._cached_autopsy: Optional[Dict[str, Any]] = None

    def analyze_last_game(self, force: bool = False) -> Dict[str, Any]:
        if not self.lcu.session or not self.lcu.port:
            if not self.lcu.connect():
                return {"status": "disconnected", "message": "Cliente LoL no detectado."}

        me = self.lcu.get_current_summoner()
        if not me or not me.get("puuid"):
            return {"status": "disconnected", "message": "Inicia sesión en el cliente de LoL."}

        puuid = me["puuid"]
        summoner_name = me.get("gameName") or me.get("displayName", "Invocador")

        # Consultar la última partida del historial
        endpoint = f"/lol-match-history/v1/products/lol/{puuid}/matches?begIndex=0&endIndex=1"
        data = self.lcu.request("GET", endpoint)
        if not data:
            return {"status": "empty", "message": "No se pudo obtener el historial reciente."}

        games = data.get("games", {}).get("games", [])
        if not games:
            return {"status": "empty", "message": "No hay partidas recientes registradas."}

        g = games[0]
        game_id = g.get("gameId")

        if not force and game_id == self._last_analyzed_game_id and self._cached_autopsy is not None:
            return self._cached_autopsy

        participants = g.get("participants", [])
        if not participants:
            return {"status": "empty", "message": "Datos de participantes no disponibles."}

        # Localizar al jugador local
        p_local = participants[0]
        for p in participants:
            if p.get("puuid") == puuid:
                p_local = p
                break

        stats = p_local.get("stats", {})
        win = stats.get("win", False)
        kills = stats.get("kills", 0)
        deaths = stats.get("deaths", 0)
        assists = stats.get("assists", 0)
        kda_ratio = round((kills + assists) / max(1, deaths), 2)

        champ_id = p_local.get("championId", 0)
        champ_name = self.lcu.get_champion_name(champ_id) or f"Campeón {champ_id}"
        champ_slug = champ_name.lower().replace("'", "").replace(" ", "").replace(".", "")

        duration_sec = g.get("gameDuration", 0)
        duration_min = max(1, duration_sec / 60)
        minions = stats.get("totalMinionsKilled", 0) + stats.get("neutralMinionsKilled", 0)
        cs_per_min = round(minions / duration_min, 1)

        team_id = p_local.get("teamId", 100)
        team_kills = sum(p.get("stats", {}).get("kills", 0) for p in participants if p.get("teamId") == team_id)
        team_deaths = sum(p.get("stats", {}).get("deaths", 0) for p in participants if p.get("teamId") == team_id)

        kill_participation = round(((kills + assists) / max(1, team_kills)) * 100) if team_kills > 0 else 0
        death_share_pct = round((deaths / max(1, team_deaths)) * 100) if team_deaths > 0 else 0

        damage_dealt = stats.get("totalDamageDealtToChampions", 0)
        gold_earned = stats.get("goldEarned", 0)
        lane = str(p_local.get("timeline", {}).get("lane", "")).lower()

        # Generar Medallas de Logro (Lo que hiciste bien)
        strengths = []
        weaknesses = []

        # 1. Supervivencia
        if deaths <= 2:
            strengths.append({
                "badge": "🛡️ Supervivencia S+",
                "title": f"Solo {deaths} { 'muerte' if deaths == 1 else 'muertes' } en toda la partida",
                "desc": "Excelente control de oleadas y posicionamiento; no regalaste presión ni oro por cazar al rival."
            })
        elif deaths <= 4:
            strengths.append({
                "badge": "🛡️ Buena Cautela A",
                "title": f"{deaths} muertes en {int(duration_min)} minutos",
                "desc": "Mantuviste un margen de riesgo controlado en la mayoría de peleas."
            })
        elif deaths >= 7:
            weaknesses.append({
                "badge": "⚠️ Riesgo Crítico: Muertes Excesivas",
                "title": f"{deaths} muertes ({death_share_pct}% de las muertes de tu equipo)",
                "desc": "Entregaste demasiado oro y tiempo muerto. Cada muerte en el juego medio/tardío abrió un objetivo (Torre/Dragón/Barón) para el rival."
            })

        # 2. Farmeo / Generación de Recursos
        if lane not in ("utility", "support"):
            if cs_per_min >= 8.2:
                strengths.append({
                    "badge": "🌾 Farmeo Maestro S+",
                    "title": f"{cs_per_min} CS/min ({minions} súbditos totales)",
                    "desc": "Ritmo de farmeo de nivel Master/Challenger. Maximizaste el ingreso de oro continuo."
                })
            elif cs_per_min >= 6.8:
                strengths.append({
                    "badge": "🌾 Buen Ritmo de Recursos A",
                    "title": f"{cs_per_min} CS/min ({minions} súbditos)",
                    "desc": "Consistencia sólida en la recolección de oleadas."
                })
            elif cs_per_min < 5.0 and duration_min > 12:
                weaknesses.append({
                    "badge": "⚠️ Déficit de Farmeo",
                    "title": f"{cs_per_min} CS/min ({minions} súbditos)",
                    "desc": "Perdiste demasiadas oleadas tras la fase de líneas. Recuerda recoger las oleadas laterales antes de agrupar en el carril central."
                })

        # 3. Participación en Bajas (Kill Participation)
        if kill_participation >= 55:
            strengths.append({
                "badge": "⚔️ Presencia Global S+",
                "title": f"{kill_participation}% de Participación en Bajas",
                "desc": "Estuviste involucrado en más de la mitad de las jugadas decisivas de tu equipo."
            })
        elif kill_participation < 30 and team_kills >= 8:
            weaknesses.append({
                "badge": "⚠️ Desconexión de Teamfights",
                "title": f"Solo {kill_participation}% de Participación",
                "desc": "Estuviste ausente en las peleas clave. Analiza si invertiste demasiado tiempo en empujar líneas sin presión de objetivos."
            })

        # 4. KDA y Eficiencia
        if kda_ratio >= 4.0:
            strengths.append({
                "badge": "👑 Dominio de Combate S",
                "title": f"{kda_ratio}:1 KDA ({kills}/{deaths}/{assists})",
                "desc": "Altísima eficiencia de daño y asistencias sin conceder bajas."
            })

        # Veredicto Principal de la Autopsia
        if win:
            verdict_title = "🏆 VICTORIA DESTACADA"
            if strengths:
                verdict_summary = f"Ganaste liderando con {strengths[0]['badge']}: {strengths[0]['title']}."
            else:
                verdict_summary = "Victoria sólida y coordinada con tu equipo para cerrar los objetivos."
        else:
            verdict_title = "💀 AUTOPSIA DE LA DERROTA"
            if weaknesses:
                verdict_summary = f"Punto crítico que inclinó la balanza: {weaknesses[0]['badge']} — {weaknesses[0]['desc']}"
            else:
                verdict_summary = "La partida se definió por superioridad rival en objetivos o peleas grupales tardías a pesar de un esfuerzo individual balanceado."

        result = {
            "status": "ready",
            "game_id": game_id,
            "win": win,
            "champion_name": champ_name,
            "champion_slug": champ_slug,
            "kills": kills,
            "deaths": deaths,
            "assists": assists,
            "kda_ratio": kda_ratio,
            "cs": minions,
            "cs_per_min": cs_per_min,
            "kill_participation": kill_participation,
            "damage_dealt": damage_dealt,
            "gold_earned": gold_earned,
            "duration_str": f"{int(duration_min)}m {duration_sec % 60:02d}s",
            "verdict_title": verdict_title,
            "verdict_summary": verdict_summary,
            "strengths": strengths,
            "weaknesses": weaknesses
        }

        self._last_analyzed_game_id = game_id
        self._cached_autopsy = result
        return result
