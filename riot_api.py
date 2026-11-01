import os
import requests
from typing import Optional, Dict, Any, List

class RiotAPIClient:
    """
    Cliente para la API Oficial de Riot Games (en la nube).
    Requiere una API Key obtenida en https://developer.riotgames.com/
    """
    # Mapeo de servidores de plataforma a clusters regionales (para Account-v1 y Match-v5)
    REGIONAL_ROUTING = {
        "la1": "americas",
        "la2": "americas",
        "na1": "americas",
        "br1": "americas",
        "euw1": "europe",
        "eun1": "europe",
        "kr": "asia",
    }

    def __init__(self, api_key: Optional[str] = None, platform: str = "la2"):
        """
        api_key: Tu clave de Riot (RGAPI-...)
        platform: Servidor principal (ej: 'la1' para LAN, 'la2' para LAS, 'na1' para NA, 'euw1' para EUW)
        """
        self.api_key = api_key or os.environ.get("RIOT_API_KEY", "")
        self.platform = platform.lower()
        self.region = self.REGIONAL_ROUTING.get(self.platform, "americas")
        
        self.session = requests.Session()
        self.session.headers.update({
            "X-Riot-Token": self.api_key,
            "Accept": "application/json"
        })

    def _get(self, base_url: str, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        if not self.api_key:
            print("[!] Advertencia: No has configurado tu RIOT_API_KEY.")
            return None

        url = f"https://{base_url}.api.riotgames.com{endpoint}"
        try:
            res = self.session.get(url, params=params, timeout=10)
            if res.status_code == 200:
                return res.json()
            elif res.status_code == 403:
                print("[!] Error 403: Tu API Key de Riot es invalida o ha expirado (recuerda que duran 24h las de desarrollo).")
            elif res.status_code == 429:
                print("[!] Error 429: Rate limit excedido de Riot API.")
            else:
                print(f"[!] Error Riot API ({res.status_code}): {res.text}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"[!] Error de conexion con Riot API: {e}")
            return None

    def get_account_by_riot_id(self, game_name: str, tag_line: str) -> Optional[Dict[str, Any]]:
        """
        Obtiene el PUUID de una cuenta usando Riot ID (Nombre#TAG).
        Usa el cluster regional (americas, europe, etc.).
        """
        endpoint = f"/riot/account/v1/accounts/by-riot-id/{game_name}/{tag_line}"
        return self._get(self.region, endpoint)

    def get_league_entries_by_puuid(self, puuid: str) -> Optional[List[Dict[str, Any]]]:
        """
        Obtiene las entradas de clasificatoria (SoloQ, Flex) para un PUUID en la plataforma actual.
        """
        # Primero obtenemos el summoner ID si es necesario o usamos el nuevo endpoint de league-v4 por puuid
        endpoint = f"/lol/league/v4/entries/by-puuid/{puuid}"
        return self._get(self.platform, endpoint)

    def get_recent_matches(self, puuid: str, count: int = 10) -> Optional[List[str]]:
        """Obtiene los IDs de las ultimas partidas jugadas."""
        endpoint = f"/lol/match/v5/matches/by-puuid/{puuid}/ids"
        return self._get(self.region, endpoint, params={"count": count, "queue": 420}) # 420 = Ranked Solo/Duo

    def get_match_details(self, match_id: str) -> Optional[Dict[str, Any]]:
        """Obtiene el detalle completo de una partida para analizar KDA, racha, etc."""
        endpoint = f"/lol/match/v5/matches/{match_id}"
        return self._get(self.region, endpoint)

if __name__ == "__main__":
    import sys
    print("[*] Modulo Riot API listo.")
    # Prueba basica si se suministra una clave
    api_key_env = os.environ.get("RIOT_API_KEY")
    if api_key_env:
        client = RiotAPIClient(api_key=api_key_env, platform="la2")
        print("[+] API Key detectada en variables de entorno. Probando conexion...")
    else:
        print("[i] Para probar este modulo, asigna tu variable de entorno RIOT_API_KEY o pasala como argumento.")
