import re
import json
import requests
from bs4 import BeautifulSoup
from typing import Dict, List, Any, Optional
from ddragon import get_ddragon

# Mapeo de estilos principales de runas en League of Legends
STYLE_NAMES = {
    8000: "Precision",
    8100: "Domination",
    8200: "Sorcery",
    8300: "Inspiration",
    8400: "Resolve"
}

# Respaldo si Data Dragon no está disponible (las runas nuevas se resuelven con ddragon.py)
RUNE_TO_STYLE = {
    # Precision (8000)
    8005: 8000, 8008: 8000, 8021: 8000, 8010: 8000,
    9101: 8000, 9111: 8000, 8009: 8000, 9104: 8000, 9105: 8000, 9103: 8000,
    8014: 8000, 8017: 8000, 8299: 8000,
    # Domination (8100)
    8112: 8100, 8128: 8100, 9923: 8100,
    8126: 8100, 8139: 8100, 8143: 8100,
    8136: 8100, 8120: 8100, 8138: 8100,
    8135: 8100, 8105: 8100, 8106: 8100,
    8137: 8100, 8140: 8100, 8141: 8100,
    # Sorcery (8200)
    8214: 8200, 8229: 8200, 8230: 8200, 8992: 8200,
    8224: 8200, 8226: 8200, 8275: 8200,
    8210: 8200, 8234: 8200, 8233: 8200,
    8237: 8200, 8232: 8200, 8236: 8200,
    # Inspiration (8300)
    8351: 8300, 8360: 8300, 8369: 8300,
    8306: 8300, 8304: 8300, 8313: 8300,
    8321: 8300, 8316: 8300, 8352: 8300,
    8410: 8300, 8347: 8300, 8345: 8300,
    # Resolve (8400)
    8437: 8400, 8439: 8400, 8465: 8400,
    8446: 8400, 8463: 8400, 8401: 8400,
    8429: 8400, 8444: 8400, 8473: 8400,
    8451: 8400, 8453: 8400, 8242: 8400,
}

# Shards / Mods nombres
STAT_SHARD_NAMES = {
    5001: "Health Scaling",
    5002: "Armor",
    5003: "Magic Resist",
    5005: "Attack Speed",
    5007: "Ability Haste",
    5008: "Adaptive Force",
    5010: "Move Speed",
    5011: "Health",
    5012: "Resist Scaling",
    5013: "Tenacity and Slow Resist"
}

# Excepciones comunes de slugs de campeones en Lolalytics
CHAMPION_SLUG_OVERRIDES = {
    "wukong": "wukong",
    "monkeyking": "wukong",
    "nunu & willump": "nunu",
    "nunu and willump": "nunu",
    "renata glasc": "renata",
}

# Diccionario de campeones multi-rol más jugados y sus líneas viables
CHAMPION_COMMON_ROLES = {
    "lux": ["middle", "support"],
    "karma": ["support", "middle", "top"],
    "swain": ["middle", "support", "bottom"],
    "nautilus": ["support", "jungle", "top"],
    "brand": ["support", "jungle", "middle"],
    "malphite": ["top", "middle", "support"],
    "yasuo": ["middle", "top"],
    "yone": ["middle", "top"],
    "gragas": ["top", "jungle", "middle"],
    "karthus": ["jungle", "bottom", "middle"],
    "seraphine": ["support", "bottom", "middle"],
    "morgana": ["support", "jungle", "middle"],
    "pantheon": ["support", "middle", "top"],
    "sett": ["top", "middle", "support"],
    "chogath": ["top", "middle"],
    "galio": ["middle", "support"],
    "tahmkench": ["top", "support"],
    "heimerdinger": ["middle", "top", "support"],
    "lucian": ["bottom", "middle"],
    "tristana": ["bottom", "middle"],
    "corki": ["middle", "bottom"],
    "quinn": ["top", "middle"],
    "teemo": ["top", "support", "jungle"],
    "shaco": ["jungle", "support"],
    "maokai": ["support", "jungle", "top"],
    "poppy": ["top", "jungle", "support"],
    "shen": ["top", "support"],
    "sion": ["top", "middle"],
    "zac": ["jungle", "top", "support"],
    "volibear": ["top", "jungle"],
    "warwick": ["jungle", "top"],
    "vayne": ["bottom", "top"],
    "smolder": ["bottom", "middle"],
    "twistedfate": ["middle", "top"],
    "jayce": ["top", "middle"],
    "kayle": ["top", "middle"],
    "kennen": ["top", "middle"],
    "rumble": ["top", "middle"],
    "olaf": ["top", "jungle"],
    "trundle": ["top", "jungle"],
    "wukong": ["jungle", "top"],
    "rengar": ["jungle", "top"],
    "diana": ["jungle", "middle"],
    "ekko": ["jungle", "middle"],
    "taliyah": ["jungle", "middle"],
    "sylas": ["middle", "top", "jungle"],
    "neeko": ["middle", "support"],
    "hwei": ["middle", "support"],
    "velkoz": ["support", "middle"],
    "xerath": ["support", "middle"],
    "zyra": ["support", "jungle", "middle"],
    "senna": ["support", "bottom"],
    "pyke": ["support", "middle"],
    "kaisa": ["bottom", "middle"]
}

class LolalyticsClient:
    BASE_URL = "https://lolalytics.com/lol"

    def __init__(self, headers: Optional[Dict[str, str]] = None):
        self.session = requests.Session()
        self.session.headers.update(headers or {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
        })
        self._counters_cache: Dict[str, Any] = {}
        self._matchups_cache: Dict[str, Any] = {}
        self._build_cache: Dict[str, Any] = {}

    def _slugify_champion(self, name: str) -> str:
        clean = name.strip().lower()
        if clean in CHAMPION_SLUG_OVERRIDES:
            return CHAMPION_SLUG_OVERRIDES[clean]
        return re.sub(r"[^a-z0-9]", "", clean)

    def _get_champion_name_by_id(self, champion_id: int) -> str:
        return get_ddragon().champion_name(champion_id) or f"Champ {champion_id}"

    def get_tierlist(self, lane: str = "all", tier: str = "emerald_plus") -> Dict[str, Any]:
        """
        Obtiene la Tier List de Lolalytics para una linea y tier especificos.
        lane: 'all', 'top', 'jungle', 'middle', 'bottom', 'support'
        tier: 'emerald_plus', 'diamond_plus', 'all', etc.
        """
        params = {}
        if lane != "all":
            params["lane"] = lane
        if tier != "emerald_plus":
            params["tier"] = tier

        url = f"{self.BASE_URL}/tierlist/"
        print(f"[*] Consultando Lolalytics (lane={lane}, tier={tier})...")
        response = self.session.get(url, params=params, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")

        # 1. Extraer el promedio de winrate del tier
        avg_winrate = 50.0
        text_content = soup.get_text()
        avg_match = re.search(r"Average\s+([A-Za-z+]+)\s+Win\s+Rate:\s*([0-9.]+)", text_content)
        if avg_match:
            avg_winrate = float(avg_match.group(2))

        # 2. Extraer el parche
        patch = "Unknown"
        patch_match = re.search(r"Patch\s+([0-9.]+)", text_content, re.IGNORECASE)
        if patch_match:
            patch = patch_match.group(1)

        print(f"[+] Parche detectado: {patch} | Average Tier Winrate: {avg_winrate}%")

        # 3. Extraer el catálogo completo de campeones desde el estado JSON de Qwik
        TIER_MAP = {
            1: "S+", 2: "S", 3: "S-", 4: "A+", 5: "A", 6: "A-",
            7: "B+", 8: "B", 9: "B-", 10: "C+", 11: "C", 12: "C-",
            13: "D+", 14: "D", 15: "D-"
        }

        champions: List[Dict[str, Any]] = []
        qwik_tag = soup.find("script", type="qwik/json")

        if qwik_tag and qwik_tag.string:
            try:
                qwik_data = json.loads(qwik_tag.string)
                objs = qwik_data.get("objs", [])

                def get_ref(val):
                    if isinstance(val, str):
                        try:
                            ref = int(val, 36)
                            if 0 <= ref < len(objs):
                                return objs[ref]
                        except Exception:
                            pass
                    return val

                champ_stats_dict = None
                for o in objs:
                    if isinstance(o, dict) and len(o) >= 50 and any(k.isdigit() for k in o.keys()):
                        k0 = next(k for k in o.keys() if k.isdigit())
                        ref = get_ref(o[k0])
                        if isinstance(ref, dict) and "wr" in ref:
                            champ_stats_dict = o
                            break

                if champ_stats_dict:
                    for cid_str, ref_str in champ_stats_dict.items():
                        stats = get_ref(ref_str)
                        if not isinstance(stats, dict):
                            continue
                        cid = int(cid_str)
                        c_name = self._get_champion_name_by_id(cid)
                        rank_val = get_ref(stats.get("rank"))
                        tier_num = get_ref(stats.get("tier"))
                        tier_str = TIER_MAP.get(tier_num, "B")
                        lane_val = get_ref(stats.get("lane")) or get_ref(stats.get("defaultLane")) or lane
                        wr_val = float(get_ref(stats.get("wr")) or 50.0)
                        delta_val = float(get_ref(stats.get("avgWrDelta")) or 0.0)
                        pr_val = float(get_ref(stats.get("pr")) or 0.0)
                        br_val = float(get_ref(stats.get("br")) or 0.0)

                        # Si se filtró por línea específica, omitir picks que no pertenecen a esa línea (rank <= 0)
                        if lane != "all" and isinstance(rank_val, int) and rank_val <= 0:
                            continue

                        champions.append({
                            "name": c_name,
                            "rank": rank_val if isinstance(rank_val, int) and rank_val > 0 else None,
                            "tier": tier_str,
                            "lane": lane_val,
                            "winrate": wr_val,
                            "delta": delta_val,
                            "pickrate": pr_val,
                            "banrate": br_val
                        })

                    champions.sort(key=lambda x: (x["rank"] is None, x["rank"] if x["rank"] is not None else 999))
                    print(f"[+] Total de campeones cargados para '{lane}': {len(champions)}")
            except Exception as e:
                print(f"[!] Error procesando Qwik tierlist: {e}")

        # 4. Fallback a filas HTML tradicionales si Qwik no arrojó resultados
        if not champions:
            rows = soup.find_all("div", class_=lambda c: c and "flex" in c and "h-[52px]" in c)
            seen_champs = set()

            for row in rows:
                cols = row.find_all("div", recursive=False)
                if len(cols) < 8:
                    continue

                name_col = cols[2]
                champ_link = name_col.find("a")
                if not champ_link:
                    continue

                champ_name = champ_link.get_text().strip()
                champ_name = re.sub(r"\s+", " ", champ_name)

                lane_img = cols[4].find("img")
                lane_detected = lane_img.get("alt", "").replace(" lane", "") if lane_img else lane
                
                champ_key = f"{champ_name}_{lane_detected}"
                if champ_key in seen_champs:
                    continue
                seen_champs.add(champ_key)

                try:
                    rank_str = cols[0].get_text().strip()
                    tier_str = cols[3].get_text().strip()
                    
                    winrate_span = cols[5].find("span")
                    winrate_val = float(winrate_span.get_text().strip()) if winrate_span else 0.0

                    pick_val = float(cols[6].get_text().strip()) if cols[6].get_text().strip() else 0.0
                    ban_val = float(cols[7].get_text().strip()) if cols[7].get_text().strip() else 0.0

                    delta = round(winrate_val - avg_winrate, 2)

                    champions.append({
                        "name": champ_name,
                        "rank": int(rank_str) if rank_str.isdigit() else None,
                        "tier": tier_str,
                        "lane": lane_detected,
                        "winrate": winrate_val,
                        "delta": delta,
                        "pickrate": pick_val,
                        "banrate": ban_val
                    })
                except Exception:
                    continue

        return {
            "patch": patch,
            "lane": lane,
            "tier_filter": tier,
            "average_winrate": avg_winrate,
            "total_champions": len(champions),
            "champions": champions
        }

    def get_champion_viable_roles(self, champion_name: str) -> List[str]:
        """
        Devuelve la lista de roles viables/populares para un campeón (ej: Lux -> ['middle', 'support']).
        """
        slug = self._slugify_champion(champion_name)
        return CHAMPION_COMMON_ROLES.get(slug, ["default"])

    def get_champion_build(self, champion_name: str, lane: Optional[str] = None, tier: str = "emerald_plus") -> Dict[str, Any]:
        """
        Extrae la build completa (Runas con IDs, Items, Orden de Habilidades y Hechizos)
        para un campeon especifico desde Lolalytics.
        """
        slug = self._slugify_champion(champion_name)
        norm_lane = lane.lower() if lane and lane.lower() != "all" else None
        if norm_lane == "mid":
            norm_lane = "middle"
        elif norm_lane == "adc":
            norm_lane = "bottom"

        cache_key = f"{slug}_{norm_lane or 'default'}_{tier}"
        if cache_key in self._build_cache:
            return self._build_cache[cache_key]

        url = f"{self.BASE_URL}/{slug}/build/"
        params = {}
        if norm_lane:
            params["lane"] = norm_lane
        if tier != "emerald_plus":
            params["tier"] = tier

        print(f"[*] Obteniendo build de {champion_name} ({slug}) [Rol: {norm_lane or 'Default'}] en Lolalytics...")
        response = self.session.get(url, params=params, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")
        qwik_tag = soup.find("script", type="qwik/json")
        if not qwik_tag or not qwik_tag.string:
            raise ValueError(f"No se pudo encontrar el estado de datos en la pagina de {champion_name}.")

        qwik_data = json.loads(qwik_tag.string)
        objs = qwik_data.get("objs", [])

        # Funcion auxiliar para resolver indices base36 recursivamente
        def resolve(val, depth=0):
            if depth > 10:
                return val
            if isinstance(val, str) and val:
                try:
                    idx = int(val, 36)
                    if idx < len(objs):
                        return resolve(objs[idx], depth + 1)
                except Exception:
                    pass
            elif isinstance(val, dict):
                return {k: resolve(v, depth + 1) for k, v in val.items()}
            elif isinstance(val, list):
                return [resolve(v, depth + 1) for v in val]
            return val

        # 1. Obtener mapas de nombres (Items, Runas, Hechizos)
        meta_obj = next((o for o in objs if isinstance(o, dict) and 'items' in o and 'runes' in o and 'spells' in o and 'champions' in o), None)
        item_names = resolve(meta_obj['items']) if meta_obj else {}
        rune_names = resolve(meta_obj['runes']) if meta_obj else {}
        spell_names = resolve(meta_obj['spells']) if meta_obj else {}

        # 2. Localizar objetos de resumen de build (Mas popular y Mayor Winrate)
        build_summaries = [o for o in objs if isinstance(o, dict) and 'skillpriority' in o and 'runes' in o and 'items' in o]
        if not build_summaries:
            raise ValueError("No se encontraron esquemas de build en el estado Qwik.")

        def format_build(summary_raw: dict, label: str) -> Dict[str, Any]:
            b = resolve(summary_raw)

            # Hechizos de Invocador (Flash, Ignite, Barrier, etc.)
            raw_sums = b.get("sums", {}).get("ids", [])
            spells = []
            for s_id in raw_sums:
                if isinstance(s_id, int) or (isinstance(s_id, str) and s_id.isdigit()):
                    s_id_int = int(s_id)
                    spells.append({
                        "id": s_id_int,
                        "name": spell_names.get(str(s_id_int), f"Spell {s_id_int}")
                    })

            # Runas
            raw_runes = b.get("runes", {})
            pri_runes_ids = [int(x) for x in raw_runes.get("set", {}).get("pri", []) if str(x).isdigit()]
            sec_runes_ids = [int(x) for x in raw_runes.get("set", {}).get("sec", []) if str(x).isdigit()]
            mod_ids = [int(x) for x in raw_runes.get("set", {}).get("mod", []) if str(x).isdigit()]

            # Determinar estilo primario y secundario (Data Dragon conoce las runas nuevas; el mapa fijo es el respaldo)
            dd = get_ddragon()
            pri_style_id = (dd.rune_style(pri_runes_ids[0]) or RUNE_TO_STYLE.get(pri_runes_ids[0], 8000)) if pri_runes_ids else 8000
            sec_style_id = (dd.rune_style(sec_runes_ids[0]) or RUNE_TO_STYLE.get(sec_runes_ids[0], 8400)) if sec_runes_ids else 8400

            # Lista plana de 9 perks para el cliente de LoL
            selected_perks = pri_runes_ids + sec_runes_ids + mod_ids

            pri_runes_formatted = [{"id": r, "name": rune_names.get(str(r), f"Perk {r}")} for r in pri_runes_ids]
            sec_runes_formatted = [{"id": r, "name": rune_names.get(str(r), f"Perk {r}")} for r in sec_runes_ids]
            mods_formatted = [{"id": m, "name": dd.shard_name(m) or STAT_SHARD_NAMES.get(m, f"Shard {m}")} for m in mod_ids]

            # Items
            items_raw = b.get("items", {})
            start_ids = [int(x) for x in items_raw.get("start", {}).get("set", []) if str(x).isdigit()]
            core_ids = [int(x) for x in items_raw.get("core", {}).get("set", []) if str(x).isdigit()]

            start_items = [{"id": i, "name": item_names.get(str(i), f"Item {i}")} for i in start_ids]
            core_items = [{"id": i, "name": item_names.get(str(i), f"Item {i}")} for i in core_ids]

            # Opciones de Late Game / Situacionales
            situational_ids = []
            seen_sit = set(core_ids + start_ids)
            for k in ["item4", "item5", "item6"]:
                for opt in items_raw.get(k, []):
                    if isinstance(opt, dict) and "id" in opt:
                        val = opt["id"]
                        if isinstance(val, int) or (isinstance(val, str) and val.isdigit()):
                            val_int = int(val)
                            if val_int not in seen_sit:
                                seen_sit.add(val_int)
                                situational_ids.append(val_int)

            situational_items = [{"id": i, "name": item_names.get(str(i), f"Item {i}")} for i in situational_ids]

            # Habilidades
            skills = {
                "priority": b.get("skillpriority", {}).get("id", "Unknown"),
                "winrate": b.get("skillpriority", {}).get("wr", 0.0),
                "games": b.get("skillpriority", {}).get("n", 0)
            }

            return {
                "type": label,
                "winrate": raw_runes.get("wr", 0.0),
                "games": raw_runes.get("n", 0),
                "summoner_spells": spells,
                "skills": skills,
                "runes": {
                    "primary_style_id": pri_style_id,
                    "primary_style_name": dd.style_name(pri_style_id) or STYLE_NAMES.get(pri_style_id, "Unknown"),
                    "sub_style_id": sec_style_id,
                    "sub_style_name": dd.style_name(sec_style_id) or STYLE_NAMES.get(sec_style_id, "Unknown"),
                    "selected_perk_ids": selected_perks,
                    "primary_runes": pri_runes_formatted,
                    "secondary_runes": sec_runes_formatted,
                    "shards": mods_formatted,
                    # Payload listo para inyectar en LCU /lol-perks/v1/pages
                    "lcu_payload": {
                        "name": f"Lolalytics - {champion_name}",
                        "primaryStyleId": pri_style_id,
                        "subStyleId": sec_style_id,
                        "selectedPerkIds": selected_perks,
                        "current": True
                    }
                },
                "items": {
                    "starting": start_items,
                    "core": core_items,
                    "situational": situational_items
                }
            }

        popular = format_build(build_summaries[0], "Most Popular")
        highest_wr = format_build(build_summaries[1], "Highest Win Rate") if len(build_summaries) > 1 else popular

        result = {
            "champion": champion_name,
            "slug": slug,
            "lane": norm_lane,
            "most_popular": popular,
            "highest_winrate": highest_wr
        }
        self._build_cache[cache_key] = result
        return result

    def get_champion_multi_builds(self, champion_name: str, requested_lane: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """
        Obtiene las builds para todos los roles viables del campeón (ej: Lux Mid y Lux Support).
        Retorna un diccionario mapeando el rol ('middle', 'support') a su build completa.
        """
        roles = list(self.get_champion_viable_roles(champion_name))
        if requested_lane and requested_lane not in roles:
            roles = [requested_lane] + roles

        builds: Dict[str, Dict[str, Any]] = {}
        for r in roles:
            lane_param = None if r == "default" else r
            try:
                b = self.get_champion_build(champion_name, lane=lane_param)
                role_key = r if r != "default" else "primary"
                builds[role_key] = b
            except Exception as e:
                print(f"[!] No se pudo obtener build de {champion_name} para {r}: {e}")

        if not builds:
            builds["primary"] = self.get_champion_build(champion_name)

        return builds

    def get_matchup_analysis(self, my_champion: str, enemy_champion: str, lane: Optional[str] = None) -> Dict[str, Any]:
        """
        Analiza el enfrentamiento directo entre dos campeones (Matchup / Counters)
        obteniendo el winrate relativo, la dificultad, objetos recomendados de counter y consejos de línea.
        """
        cache_key = f"{my_champion.lower()}_vs_{enemy_champion.lower()}_{lane or 'all'}"
        if cache_key in self._matchups_cache:
            return self._matchups_cache[cache_key]

        my_slug = self._slugify_champion(my_champion)
        enemy_slug = self._slugify_champion(enemy_champion)

        url = f"{self.BASE_URL}/{my_slug}/vs/{enemy_slug}/build/"
        params = {}
        if lane and lane in ["top", "jungle", "middle", "bottom", "support"]:
            params["lane"] = lane
            params["vslane"] = lane

        print(f"[*] Consultando enfrentamiento {my_champion} vs {enemy_champion} en Lolalytics...")
        res = self.session.get(url, params=params, timeout=12)
        if res.status_code != 200:
            raise ValueError(f"No se pudo cargar el matchup de {my_champion} vs {enemy_champion}")

        text = BeautifulSoup(res.text, "lxml").get_text()

        wr = 50.0
        delta = 0.0
        games = 0

        match_wr = re.search(r"wins against [^0-9]+ ([0-9.]+)% of the time", text, re.IGNORECASE)
        if match_wr:
            wr = float(match_wr.group(1))

        match_delta = re.search(r"wins against [^0-9]+ ([+-]?[0-9.]+)% different than would be expected", text, re.IGNORECASE)
        if match_delta:
            delta = float(match_delta.group(1))

        match_games = re.search(r"([0-9.]+)%\s*Win\s*Rate\s*([0-9,]+)\s*Games", text)
        if match_games:
            games = int(match_games.group(2).replace(",", ""))

        if wr >= 52.5 or delta >= 1.5:
            difficulty = "Favorable (Tienes Ventaja)"
            diff_level = "easy"
            tip = f"Tienes ventaja natural en este enfrentamiento ({wr}% WR). Juega proactivo, presiona desde los primeros niveles y castiga sus enfriamientos."
        elif wr <= 48.5 or delta <= -1.5:
            difficulty = "Desfavorable (Counter / En Desventaja)"
            diff_level = "hard"
            tip = f"El rival tiene ventaja estadística en este matchup ({wr}% WR). Prioriza el control de oleadas bajo tu torre, evita duelos 1v1 extendidos y coordina emboscadas con tu jungla."
        else:
            difficulty = "Skill Matchup (Duelo Equilibrado)"
            diff_level = "skill"
            tip = f"Enfrentamiento de pura habilidad ({wr}% WR). Quien cometa el primer error o consiga el pico de nivel 2 / 6 tomará la iniciativa."

        # Identificación de arquetipos y objetos counter
        HEAVY_HEALERS = {"aatrox", "vladimir", "warwick", "fiora", "sylas", "drmundo", "briar", "swain", "illaoi", "soraka", "yuumi", "nasus", "kayn", "olaf", "trundle"}
        HEAVY_AD_BURST = {"zed", "talon", "qiyana", "rengar", "khazix", "naafiri", "pyke", "pantheon", "draven", "kayn", "jayce"}
        HEAVY_AP_BURST = {"syndra", "lux", "zoe", "veigar", "leblanc", "vex", "xerath", "ahri", "viktor", "anivia", "kassadin"}
        HARD_CC = {"malzahar", "skarner", "mordekaiser", "warwick", "morgana", "leona", "nautilus", "lissandra", "amumu"}
        TANKS = {"chogath", "sion", "ornn", "malphite", "tahmkench", "ksante", "sejuani", "maokai", "zac", "rammus"}
        ATTACK_SPEED = {"masteryi", "belveth", "yasuo", "yone", "jax", "irelia", "vayne", "kogmaw", "kalista"}
        STEALTH = {"akali", "shaco", "evelynn", "teemo", "twitch"}

        counter_items = []
        counter_notes = []

        if enemy_slug in HEAVY_HEALERS:
            counter_items.append("Heridas Graves (Chaleco de Zarzas / Verdugo / Orbe del Olvido)")
            counter_notes.append("Anti-Curación: Corta su sustento temprano para ganar intercambios.")
        if enemy_slug in HEAVY_AD_BURST:
            counter_items.append("Punteras de Acero (Tabis) / Reloj de Arena de Zhonya")
            counter_notes.append("Defensa AD: Mitiga su daño explosivo físico y no te expongas a nivel 6.")
        if enemy_slug in HEAVY_AP_BURST:
            counter_items.append("Botas de Mercurio / Fauces de Malmortius / Velo de Banshee")
            counter_notes.append("Defensa Mágica: Absorbe sus rotaciones de hechizos y esquiva su pokeo.")
        if enemy_slug in HARD_CC:
            counter_items.append("Fajín de Mercurio (QSS) / Runa de Tenacidad")
            counter_notes.append("Anti-Supresión: Quita su control crítico con QSS para salvarte de ganks.")
        if enemy_slug in TANKS:
            counter_items.append("Rey Arruinado (Bork) / Lord Dominik / Tormento de Liandry")
            counter_notes.append("Anti-Tanque: Necesitas daño por porcentaje de vida máxima y penetración.")
        if enemy_slug in ATTACK_SPEED:
            counter_items.append("Corazón de Hielo / Presagio de Randuin")
            counter_notes.append("Reducción de AS: Neutraliza su daño por segundo y críticos.")
        if enemy_slug in STEALTH:
            counter_items.append("Lente del Oráculo (Lente Rojo) / Guardianes de Control")
            counter_notes.append("Visión: Revela su posición en humo o sigilo durante el intercambio.")

        result = {
            "my_champion": my_champion,
            "enemy_champion": enemy_champion,
            "winrate": wr,
            "normalized_delta": delta,
            "games": games,
            "difficulty": difficulty,
            "diff_level": diff_level,
            "tip": tip,
            "counter_items": counter_items,
            "counter_notes": counter_notes
        }
        self._matchups_cache[cache_key] = result
        return result

    def get_champion_counters(self, champion_name: str, lane: Optional[str] = None) -> Dict[str, Any]:
        """
        Extrae los counters directos de un campeón desde Lolalytics:
        - worst: Los 5 campeones que más le ganan (Peores Matchups / Counters rivales)
        - best: Los 5 campeones a los que más destroza (Mejores Matchups / Presas Fáciles)
        """
        cache_key = f"{champion_name.lower()}_{lane or 'all'}"
        if cache_key in self._counters_cache:
            return self._counters_cache[cache_key]

        slug = self._slugify_champion(champion_name)
        url = f"{self.BASE_URL}/{slug}/counters/"
        params = {}
        if lane and lane in ["top", "jungle", "middle", "bottom", "support"]:
            params["lane"] = lane

        print(f"[*] Obteniendo lista de counters de {champion_name} ({lane or 'general'}) en Lolalytics...")
        res = self.session.get(url, params=params, timeout=12)
        if res.status_code != 200:
            raise ValueError(f"No se pudieron cargar los counters de {champion_name}")

        soup = BeautifulSoup(res.text, "lxml")
        cards = soup.find_all("div", class_=re.compile(r"h-\[254px\]"))

        parsed = []
        for c in cards:
            a = c.find("a", href=re.compile(r"/vs/([a-z0-9]+)/build/"))
            if not a:
                continue
            enemy_slug = re.search(r"/vs/([a-z0-9]+)/build/", a.get("href")).group(1)
            name_el = c.find("div", class_=re.compile(r"border-b-\[1px\]"))
            name = name_el.get_text(strip=True) if name_el else enemy_slug.capitalize()

            full_text = c.get_text(separator=" ", strip=True)
            wr_match = re.search(r"([0-9.]+) ?%", full_text)
            wr = float(wr_match.group(1)) if wr_match else 50.0

            games_match = re.search(r"([0-9,]+) Games", full_text)
            games = int(games_match.group(1).replace(",", "")) if games_match else 0

            avatar_url = f"https://cdn5.lolalytics.com/champx46/{enemy_slug}.webp"
            parsed.append({
                "name": name,
                "slug": enemy_slug,
                "winrate": wr,
                "games": games,
                "avatar_url": avatar_url
            })

        # Filtrar muestras confiables (mínimo 100 partidas si existen)
        valid = [p for p in parsed if p["games"] >= 100] or parsed
        worst = sorted(valid, key=lambda x: x["winrate"])[:5]
        best = sorted(valid, key=lambda x: x["winrate"], reverse=True)[:5]

        result = {
            "champion": champion_name,
            "lane": lane or "all",
            "worst": worst,
            "best": best
        }
        self._counters_cache[cache_key] = result
        return result

if __name__ == "__main__":
    client = LolalyticsClient()
    
    # Prueba con un campeon
    champ = "Jinx"
    build_data = client.get_champion_build(champ)
    
    pop = build_data["most_popular"]
    print(f"\n==========================================")
    print(f" BUILD RECOMENDADA DE LOLALYTICS: {champ.upper()}")
    print(f"==========================================")
    print(f"Winrate: {pop['winrate']}% ({pop['games']:,} partidas)")
    print(f"Hechizos: {' + '.join(s['name'] for s in pop['summoner_spells'])}")
    print(f"Maxeo Habilidades: {pop['skills']['priority']}")
    
    r = pop["runes"]
    print(f"\n[RUNAS]")
    print(f"Rama Principal ({r['primary_style_name']}):")
    for perk in r["primary_runes"]:
        print(f"  • {perk['name']} (ID: {perk['id']})")
    print(f"Rama Secundaria ({r['sub_style_name']}):")
    for perk in r["secondary_runes"]:
        print(f"  • {perk['name']} (ID: {perk['id']})")
    print(f"Estadisticas (Shards):")
    for s in r["shards"]:
        print(f"  • {s['name']} (ID: {s['id']})")

    print(f"\n[ITEMS RECOMENDADOS]")
    print(f"Iniciales: {', '.join(i['name'] for i in pop['items']['starting'])}")
    print(f"Core Build: {' -> '.join(i['name'] for i in pop['items']['core'])}")

    print("\nPayload LCU listo para auto-importar:")
    print(json.dumps(r["lcu_payload"], indent=2))
