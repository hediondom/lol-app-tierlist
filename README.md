# LoL Companion App - Asistente de Escritorio para League of Legends

Aplicación de escritorio moderna estilo **Porofessor / Mobalytics** desarrollada con:
- **Frontend Web**: HTML5, CSS3 Gamer Dark Mode y JavaScript.
- **Ventana Nativa**: Motor Chromium WebView2 (ultraligero, ~40MB RAM).
- **Backend**: Python conectándose a **Lolalytics** y a la **API Local del Cliente LoL (LCU)**.

---

## 🚀 Cómo Iniciar la Aplicación

### Opción 1: Ejecutable Compilado (.exe)
Ya se encuentra compilado y listo para usar:
- Archivo: `dist\LoLCompanion\LoLCompanion.exe`
- Puedes crearle un acceso directo en tu escritorio haciendo clic derecho en `LoLCompanion.exe` -> **"Enviar a" -> "Escritorio (crear acceso directo)"**.

Para volver a compilarlo tú mismo en cualquier momento, solo haz doble clic en [build_exe.bat](file:///C:/Users/agust/.gemini/antigravity/scratch/lol-companion/build_exe.bat).

### Opción 2: Desde el Código Fuente
Hacer **doble clic en `run_app.bat`** o ejecutar:
```bash
python app_gui.py
```

---

## 🌟 Funcionalidades en la Interfaz

1. **🏆 Meta & Tier List (Lolalytics en Tiempo Real):**
   - Filtros por rol: General, Top, Jungle, Mid, ADC, Support.
   - Tabla con Avatares, Tiers (S+, S, A), Winrates y Delta normalizado.
   - Al hacer clic en cualquier campeón, se abre automáticamente su build.

2. **⚡ Builds & Runas:**
   - Buscador de campeón con acceso rápido.
   - Árbol visual de runas: Rama Principal, Rama Secundaria y Shards de estadísticas.
   - Objetos recomendados (Iniciales y Core Build) y orden de habilidades (Q > W > E).
   - Botón **"Inyectar Runas al Cliente de LoL"** con 1 clic.

3. **👥 Scouting de Lobby & Pantalla de Carga:**
   - Detecta Selección de Campeones y Pantalla de Carga / In-Game en tiempo real.
   - **⚖️ Balance de Equipos & Probabilidad de Victoria:** Panel panorámico superior que compara a ambas escuadras con barra de probabilidad dual, veredicto estratégico, análisis de composición de daño (AD/AP/Tanque) con alertas tácticas, y focos prioritarios (MVP Aliado, Mayor Amenaza Rival y Objetivo Vulnerable).
   - Revela a los 10 jugadores (aliados y rivales) sin censura ni anonimato en partida.
   - Badges automáticos de rachas y estilo de juego (`[!] EN RACHA`, `[!] TILT WARNING`, etc.).
   - Muestra el enfrentamiento directo de tu carril con winrate, dificultad y consejos tácticos.

4. **🥊 Análisis de Matchups & Counters:**
   - Comparador 1v1 directo entre cualquier pareja de campeones con winrate relativo, dificultad y objetos counter.
   - Explorador de Counters: Revela los 5 peores enfrentamientos (counters rivales) y las 5 presas fáciles de cualquier campeón.

5. **👤 Mi Perfil & Historial de Partidas (Estilo OP.GG):**
   - **Rangos Actuales:** Tarjetas visuales de Ranked Solo/Duo y Ranked Flex con LP, winrate y victorias/derrotas.
   - **Campeones Más Jugados:** Estadísticas completas de tus campeones más usados (KDA, CS promedio, winrate y partidas).
   - **Resumen Reciente:** Gráfico donut de winrate, ratio KDA global, porcentaje de participación en asesinatos (P/Kill) y barras de roles preferidos (Top, Jg, Mid, ADC, Supp).
   - **Historial de Partidas:** Tarjetas detalladas de tus últimas 20 partidas (Victoria en azul / Derrota en rojo, KDA, CS/min, 6 objetos finales + baratija, hechizos y vista previa de los 10 jugadores).
   - **Filtros rápidos:** Filtra instantáneamente por Todas, SoloQ, Flex, Normal o ARAM.

6. **🖥️ Superponer App sobre el Juego (Atajo Global `Ctrl + X`):**
   - **Tecla de Acceso Rápido Configurable:** Presiona **`Ctrl + X`** (o tu combinación preferida: `Ctrl + X`, `Ctrl + O`, `F2`, `F6`, etc.) para traer instantáneamente la interfaz completa de la app al frente superpuesta sobre League of Legends.
   - Vuelve a presionar **`Ctrl + X`** para minimizarla y regresar al juego sin interrupciones.
   - *Nota:* Para que la app se dibuje directamente por encima de League of Legends, asegúrate de tener el juego configurado en **"Ventana sin bordes" (Borderless)** en las opciones de video de LoL (como Porofessor y Blitz).

6. **⚡ Auto-Runas & Objetos en la Tienda del Juego:**
   - Aplica runas e inyecta la lista de objetos de Lolalytics directamente en la tienda de LoL (tecla `P`).
