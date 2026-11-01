import os
import time
from lolalytics import LolalyticsClient
from lcu_connector import LCUConnector
from riot_api import RiotAPIClient
from auto_runes import AutoRuneService
from scout import ScoutService

def banner():
    print("=" * 60)
    print("        LOL COMPANION - MOTOR PRINCIPAL (MVP)")
    print("    Lolalytics Scraper + LCU Local + Riot Cloud API")
    print("=" * 60)

def menu():
    print("\nSelecciona una accion:")
    print("1. Ver Tier List de Lolalytics por linea")
    print("2. Consultar Build y Runas de un Campeon")
    print("3. Scouting de Aliados (Escanear Lobby actual)")
    print("4. Activar Vigilante en vivo (Scouting de Aliados + Auto-Runas)")
    print("5. Probar conexion con el Cliente de LoL local (LCU)")
    print("6. Salir")
    return input("\nOpcion [1-6]: ").strip()

def run_scout_lobby():
    scout = ScoutService()
    scout.scout_current_lobby()

def run_champion_build():
    champ_name = input("\nIngresa el nombre del campeon (ej: Jinx, Aatrox, Thresh): ").strip()
    if not champ_name:
        return
    client = LolalyticsClient()
    try:
        data = client.get_champion_build(champ_name)
        pop = data["most_popular"]
        print(f"\n==========================================")
        print(f" BUILD LOLALYTICS: {champ_name.upper()}")
        print(f"==========================================")
        print(f"Winrate: {pop['winrate']}% ({pop['games']:,} partidas)")
        print(f"Hechizos: {' + '.join(s['name'] for s in pop['summoner_spells'])}")
        print(f"Maxeo Habilidades: {pop['skills']['priority']}")
        
        r = pop["runes"]
        print(f"\n[RUNAS]")
        print(f"Rama Principal ({r['primary_style_name']}):")
        for perk in r["primary_runes"]:
            print(f"  - {perk['name']} (ID: {perk['id']})")
        print(f"Rama Secundaria ({r['sub_style_name']}):")
        for perk in r["secondary_runes"]:
            print(f"  - {perk['name']} (ID: {perk['id']})")
        print(f"Estadisticas (Shards):")
        for s in r["shards"]:
            print(f"  - {s['name']} (ID: {s['id']})")

        print(f"\n[ITEMS RECOMENDADOS]")
        print(f"Iniciales: {', '.join(i['name'] for i in pop['items']['starting'])}")
        print(f"Core Build: {' -> '.join(i['name'] for i in pop['items']['core'])}")
    except Exception as e:
        print(f"[!] Error obteniendo build de {champ_name}: {e}")

def run_lolalytics_tierlist():
    client = LolalyticsClient()
    lane = input("Ingresa linea (all, top, jungle, middle, bottom, support) [all]: ").strip() or "all"
    data = client.get_tierlist(lane=lane)
    
    print(f"\n--- TOP 15 CAMPEONES EN {lane.upper()} (Parche {data['patch']}) ---")
    print(f"{'#':<3} {'Tier':<5} {'Campeon':<14} {'Rol':<8} {'WR Real':<9} {'WR Delta':<9} {'Pick':<7} {'Ban':<7}")
    print("-" * 65)
    for c in data["champions"][:15]:
        sign = "+" if c["delta"] >= 0 else ""
        delta_str = f"{sign}{c['delta']}%"
        print(f"{c['rank'] or '-':<3} {c['tier']:<5} {c['name']:<14} {c['lane']:<8} {c['winrate']:<9}% {delta_str:<9} {c['pickrate']:<7}% {c['banrate']:<7}%")

def test_lcu_connection():
    connector = LCUConnector()
    print("[*] Intentando conectar con el cliente de LoL...")
    if connector.connect():
        print(f"[+] Conectado exitosamente en el puerto {connector.port}!")
        summoner = connector.get_current_summoner()
        if summoner:
            name = summoner.get('gameName') or summoner.get('displayName')
            tag = summoner.get('tagLine', '')
            print(f"    Invocador: {name}#{tag} (Nivel {summoner.get('summonerLevel')})")
        else:
            print("    No se pudo leer la informacion del invocador.")
    else:
        print("[X] No se encontro el cliente de League of Legends abierto.")

def watch_champ_select():
    service = AutoRuneService(mode="most_popular")
    service.start()

def main():
    banner()
    while True:
        op = menu()
        if op == "1":
            run_lolalytics_tierlist()
        elif op == "2":
            run_champion_build()
        elif op == "3":
            run_scout_lobby()
        elif op == "4":
            watch_champ_select()
        elif op == "5":
            test_lcu_connection()
        elif op == "6":
            print("\n¡Hasta luego!")
            break
        else:
            print("[!] Opcion no valida.")

if __name__ == "__main__":
    main()
