"""
Datos estáticos del juego desde Data Dragon (y CommunityDragon para los fragmentos de runas):
catálogo de campeones con sus clases, ramas de runas, hechizos de invocador e iconos.

Se guardan en %APPDATA%\\LoLCompanion\\ddragon (un archivo por parche) y se actualizan en segundo
plano cuando sale un parche nuevo, así la app no depende de los datos con los que se compiló.
Sin conexión usa lo último guardado o, la primera vez, el catálogo de campeones empaquetado.
"""
import os
import re
import sys
import json
import threading
import requests
from typing import Any, Dict, Optional, Tuple

DDRAGON_URL = "https://ddragon.leagueoflegends.com"
CDRAGON_PERKS_URL = "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perks.json"
CDRAGON_ASSETS_URL = "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/"
FALLBACK_VERSION = "14.21.1"

# Campeones cuyas puntuaciones de Data Dragon (info.attack / info.magic) dan una clase de daño incorrecta
DAMAGE_TYPE_OVERRIDES = {"Belveth": "ad", "Gwen": "ap", "Qiyana": "ad"}


def _cache_dir() -> str:
    return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "LoLCompanion", "ddragon")


def _bundled_dir() -> str:
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def _version_key(version: str) -> Tuple[int, ...]:
    """'16.21.1' -> (16, 21, 1); () si no es una versión."""
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError:
        return ()


def _normalize(name: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class DataDragon:
    def __init__(self, cache_dir: Optional[str] = None):
        self.cache_dir = cache_dir or _cache_dir()
        self._refresh_lock = threading.Lock()
        self._set_data({})
        self._load_from_disk()

    # ------------------------------------------------------------------ carga

    def _set_data(self, data: Dict[str, Any]):
        """Reemplaza todos los datos de una vez: una lectura concurrente ve el conjunto viejo o el nuevo."""
        champions = {int(k): {**v, "key": int(k)} for k, v in data.get("champions", {}).items()}
        by_name = {}
        for key, champ in champions.items():
            for alias in (champ.get("name"), champ.get("id")):
                if _normalize(alias):
                    by_name[_normalize(alias)] = key
        self._data = {
            "version": data.get("version"),
            "champions": champions,
            "by_name": by_name,
            "styles": {int(k): v for k, v in data.get("styles", {}).items()},
            "runes": {int(k): v for k, v in data.get("runes", {}).items()},
            "spells": {int(k): v for k, v in data.get("spells", {}).items()},
            "shards": {int(k): v for k, v in data.get("shards", {}).items()},
        }

    def _load_from_disk(self):
        """Carga el último parche guardado; si no hay ninguno, el catálogo de campeones empaquetado."""
        versions = []
        if os.path.isdir(self.cache_dir):
            versions = [f[:-5] for f in os.listdir(self.cache_dir) if f.endswith(".json") and _version_key(f[:-5])]
        for version in sorted(versions, key=_version_key, reverse=True):
            try:
                with open(os.path.join(self.cache_dir, f"{version}.json"), "r", encoding="utf-8") as f:
                    self._set_data(json.load(f))
                return
            except (OSError, ValueError):
                continue

        try:
            with open(os.path.join(_bundled_dir(), "champions_cache.json"), "r", encoding="utf-8") as f:
                names = json.load(f)
            with open(os.path.join(_bundled_dir(), "champions_folder_cache.json"), "r", encoding="utf-8") as f:
                folders = json.load(f)
            self._set_data({"champions": {k: {"id": folders.get(k, ""), "name": v, "tags": [], "info": {}}
                                          for k, v in names.items()}})
        except (OSError, ValueError) as e:
            print(f"[!] No se pudo cargar el catálogo de campeones empaquetado: {e}")

    def refresh(self) -> bool:
        """Descarga los datos del último parche si cambió. Devuelve True si los datos quedan al día."""
        with self._refresh_lock:
            try:
                latest = requests.get(f"{DDRAGON_URL}/api/versions.json", timeout=5).json()[0]
                if latest == self._data["version"]:
                    return True
                cdn = f"{DDRAGON_URL}/cdn/{latest}/data/en_US"
                champions = requests.get(f"{cdn}/champion.json", timeout=10).json()["data"]
                styles = requests.get(f"{cdn}/runesReforged.json", timeout=10).json()
                spells = requests.get(f"{cdn}/summoner.json", timeout=10).json()["data"]

                data = {
                    "version": latest,
                    "champions": {c["key"]: {"id": c["id"], "name": c["name"], "tags": c.get("tags", []), "info": c.get("info", {})}
                                  for c in champions.values()},
                    "styles": {},
                    "runes": {},
                    "spells": {s["key"]: {"id": s["id"], "name": s["name"]} for s in spells.values()},
                    "shards": self._fetch_shards(),
                }
                for style in styles:
                    data["styles"][style["id"]] = {"name": style["name"], "icon": style["icon"]}
                    for slot in style.get("slots", []):
                        for rune in slot.get("runes", []):
                            data["runes"][rune["id"]] = {"style": style["id"], "name": rune["name"], "icon": rune["icon"]}
            except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as e:
                print(f"[!] No se pudieron actualizar los datos de Data Dragon: {e}")
                return False

            self._save(data)
            self._set_data(data)
            print(f"[+] Datos de Data Dragon actualizados al parche {latest}")
            return True

    @staticmethod
    def _fetch_shards() -> Dict[int, Dict[str, str]]:
        """Nombres e iconos de los fragmentos de estadísticas (Data Dragon no los incluye)."""
        try:
            perks = requests.get(CDRAGON_PERKS_URL, timeout=10).json()
            return {p["id"]: {"name": p["name"],
                              "icon": CDRAGON_ASSETS_URL + p["iconPath"].replace("/lol-game-data/assets/", "").lower()}
                    for p in perks if 5000 <= p.get("id", 0) < 6000 and p.get("iconPath")}
        except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError) as e:
            print(f"[!] No se pudieron cargar los fragmentos de runas desde CommunityDragon: {e}")
            return {}

    def _save(self, data: Dict[str, Any]):
        """Guarda el parche descargado y borra los anteriores."""
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            current = f"{data['version']}.json"
            with open(os.path.join(self.cache_dir, current), "w", encoding="utf-8") as f:
                json.dump(data, f)
            for name in os.listdir(self.cache_dir):
                if name != current and name.endswith(".json") and _version_key(name[:-5]):
                    os.remove(os.path.join(self.cache_dir, name))
        except OSError as e:
            print(f"[!] No se pudo guardar la caché de Data Dragon: {e}")

    # ------------------------------------------------------------- consultas

    @property
    def version(self) -> str:
        return self._data["version"] or FALLBACK_VERSION

    def _champion(self, champion: Any) -> Optional[Dict[str, Any]]:
        """Busca por ID numérico, nombre ("Wukong") o identificador interno ("MonkeyKing")."""
        key = _to_int(champion)
        if key is None:
            key = self._data["by_name"].get(_normalize(champion))
        return self._data["champions"].get(key)

    def champion_id(self, champion: Any) -> Optional[int]:
        champ = self._champion(champion)
        return champ["key"] if champ else None

    def champion_name(self, champion: Any) -> Optional[str]:
        champ = self._champion(champion)
        return champ["name"] if champ else None

    def champion_folder(self, champion: Any) -> Optional[str]:
        """Identificador interno del campeón (ej. 'MonkeyKing'), usado en carpetas y URLs."""
        champ = self._champion(champion)
        return (champ.get("id") or None) if champ else None

    def damage_type(self, champion: Any) -> Optional[str]:
        """'tank', 'ap' o 'ad' según las etiquetas y puntuaciones de Data Dragon (None si no se conoce)."""
        champ = self._champion(champion)
        if not champ or not champ.get("tags"):
            return None
        if champ.get("id") in DAMAGE_TYPE_OVERRIDES:
            return DAMAGE_TYPE_OVERRIDES[champ["id"]]
        tags, info = champ["tags"], champ.get("info", {})
        if tags[0] == "Tank" or (tags[0] == "Support" and "Tank" in tags):
            return "tank"
        if tags[0] == "Mage" or (tags[0] == "Support" and "Mage" in tags):
            return "ap"
        return "ap" if info.get("magic", 0) > info.get("attack", 0) else "ad"

    def rune_style(self, rune_id: Any) -> Optional[int]:
        rune = self._data["runes"].get(_to_int(rune_id))
        return rune["style"] if rune else None

    def style_name(self, style_id: Any) -> Optional[str]:
        style = self._data["styles"].get(_to_int(style_id))
        return style["name"] if style else None

    def shard_name(self, shard_id: Any) -> Optional[str]:
        shard = self._data["shards"].get(_to_int(shard_id))
        return shard["name"] if shard else None

    def perk_icon_url(self, perk_id: Any) -> Optional[str]:
        """Icono de una runa (Data Dragon) o de un fragmento de estadísticas (CommunityDragon)."""
        perk_id = _to_int(perk_id)
        rune = self._data["runes"].get(perk_id)
        if rune:
            return f"{DDRAGON_URL}/cdn/img/{rune['icon']}"
        shard = self._data["shards"].get(perk_id)
        return shard["icon"] if shard else None

    def style_icon_url(self, style_id: Any) -> Optional[str]:
        style = self._data["styles"].get(_to_int(style_id))
        return f"{DDRAGON_URL}/cdn/img/{style['icon']}" if style else None

    def spell_key_name(self, spell_key: Any) -> Optional[str]:
        """Identificador interno del hechizo (4 -> 'SummonerFlash'), usado en las URLs de iconos."""
        spell = self._data["spells"].get(_to_int(spell_key))
        return spell["id"] if spell else None

    def spell_icon_url(self, spell_key: Any) -> Optional[str]:
        spell_id = self.spell_key_name(spell_key)
        return f"{DDRAGON_URL}/cdn/{self.version}/img/spell/{spell_id}.png" if spell_id else None


_instance: Optional[DataDragon] = None
_instance_lock = threading.Lock()


def get_ddragon() -> DataDragon:
    """Instancia compartida: carga lo guardado al instante y busca un parche nuevo en segundo plano."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = DataDragon()
            threading.Thread(target=_instance.refresh, daemon=True).start()
    return _instance
