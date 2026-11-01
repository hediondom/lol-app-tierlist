// Estado global de la aplicacion en el frontend
let currentLane = 'all';
let currentLoadedBuild = null;
let autoRunesEnabled = true;
let autoOverlayEnabled = true;
let lastScoutedPhase = null;

document.addEventListener('DOMContentLoaded', () => {
    initTabs();
    initSidebar();
    initLaneFilters();
    initTableSort();
    initSearch();
    initToggle();
    initMatchupSearch();
    initProfile();

    // Esperar a que la API de PyWebView este disponible
    window.addEventListener('pywebviewready', () => {
        console.log("[+] PyWebView API conectado exitosamente.");
        loadTierlist('all');
        checkLoLStatus();

        if (window.pywebview.api.get_configured_hotkey) {
            window.pywebview.api.get_configured_hotkey().then(savedKey => {
                const sel = document.getElementById('hotkeySelector');
                if (sel && savedKey) {
                    sel.value = savedKey;
                }
            });
        }

        // Monitoreo continuo de estado cada 3 segundos
        setInterval(checkLoLStatus, 3000);
    });
});

// Navegacion entre Pestañas
function initTabs() {
    const tabs = document.querySelectorAll('.nav-tab');
    const panes = document.querySelectorAll('.tab-pane');

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            tabs.forEach(t => t.classList.remove('active'));
            panes.forEach(p => p.classList.remove('active'));

            tab.classList.add('active');
            const targetId = tab.getAttribute('data-tab');
            document.getElementById(targetId).classList.add('active');

            if (targetId === 'scout-tab') {
                refreshLobby();
            } else if (targetId === 'profile-tab') {
                loadUserProfile();
            }
        });
    });
}

// Control del Menú Lateral (Sidebar)
function initSidebar() {
    const sidebar = document.getElementById('appSidebar');
    const toggleBtn = document.getElementById('sidebarToggleBtn');
    const collapseBtn = document.getElementById('sidebarCollapseBtn');

    const toggleSidebar = () => {
        if (!sidebar) return;
        const isCollapsed = sidebar.classList.toggle('collapsed');
        localStorage.setItem('lol_companion_sidebar_collapsed', isCollapsed ? '1' : '0');
    };

    if (toggleBtn) toggleBtn.addEventListener('click', toggleSidebar);
    if (collapseBtn) collapseBtn.addEventListener('click', toggleSidebar);

    // Restaurar preferencia previa del usuario
    if (localStorage.getItem('lol_companion_sidebar_collapsed') === '1' && sidebar) {
        sidebar.classList.add('collapsed');
    }
}

// Filtros por linea en Tier List
function initLaneFilters() {
    const buttons = document.querySelectorAll('.lane-btn');
    buttons.forEach(btn => {
        btn.addEventListener('click', () => {
            buttons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentLane = btn.getAttribute('data-lane');
            loadTierlist(currentLane);
        });
    });
}

// Buscador de Campeones
function initSearch() {
    const input = document.getElementById('champSearchInput');
    const btn = document.getElementById('searchBtn');

    const handleSearch = () => {
        const query = input.value.trim();
        if (query) {
            loadBuild(query);
        }
    };

    btn.addEventListener('click', handleSearch);
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') handleSearch();
    });

    document.getElementById('applyRunesBtn').addEventListener('click', () => {
        if (!currentLoadedBuild) return;
        const champName = currentLoadedBuild.champion;
        if (window.pywebview && window.pywebview.api) {
            window.pywebview.api.apply_runes_and_items(champName).then(success => {
                if (success) {
                    alert(`¡Runas y Conjunto de Objetos para ${champName} aplicados!\n\nLos objetos aparecerán en la tienda del juego al presionar la tecla P.`);
                } else {
                    alert('No se pudo aplicar. Asegúrate de tener el LoL abierto.');
                }
            });
        }
    });

    document.getElementById('refreshLobbyBtn').addEventListener('click', () => refreshLobby(true));
}

// Switch de Auto-Runas y Selector de Atajo para Superponer App
function initToggle() {
    const runeToggle = document.getElementById('toggleSwitch');
    if (runeToggle) {
        runeToggle.addEventListener('click', () => {
            autoRunesEnabled = !autoRunesEnabled;
            runeToggle.classList.toggle('active', autoRunesEnabled);
            if (window.pywebview && window.pywebview.api) {
                window.pywebview.api.set_auto_runes(autoRunesEnabled);
            }
        });
    }

    const hotkeySelector = document.getElementById('hotkeySelector');
    if (hotkeySelector) {
        hotkeySelector.addEventListener('change', (e) => {
            const selectedKey = e.target.value;
            if (window.pywebview && window.pywebview.api) {
                window.pywebview.api.set_hotkey_config(selectedKey).then(ok => {
                    if (ok) {
                        console.log(`[+] Tecla rápida actualizada a ${selectedKey.toUpperCase()}`);
                    }
                });
            }
        });
    }
}

// 1. Cargar y Ordenar Tier List desde Python
const TIER_SORT_WEIGHT = {
    'S+': 15, 'S': 14, 'S-': 13,
    'A+': 12, 'A': 11, 'A-': 10,
    'B+': 9,  'B': 8,  'B-': 7,
    'C+': 6,  'C': 5,  'C-': 4,
    'D+': 3,  'D': 2,  'D-': 1
};

let currentTierlistData = null;
let currentSortKey = 'rank';
let currentSortDirection = 'asc';

function initTableSort() {
    const headers = document.querySelectorAll('th[data-sort]');
    headers.forEach(th => {
        th.addEventListener('click', () => {
            const key = th.getAttribute('data-sort');
            if (currentSortKey === key) {
                currentSortDirection = (currentSortDirection === 'asc') ? 'desc' : 'asc';
            } else {
                currentSortKey = key;
                // Por defecto: Porcentajes y Tiers ordenan descendente primero (mejor a peor)
                // Nombres, roles y rank numérico ordenan ascendente primero (1, 2, 3 o A-Z)
                currentSortDirection = (key === 'rank' || key === 'name' || key === 'lane') ? 'asc' : 'desc';
            }
            renderTierlistTable();
        });
    });
}

function sortChampions(champions, key, direction) {
    const mult = direction === 'asc' ? 1 : -1;
    return [...champions].sort((a, b) => {
        if (key === 'rank') {
            const rA = a.rank != null ? a.rank : 999;
            const rB = b.rank != null ? b.rank : 999;
            return (rA - rB) * mult;
        }
        if (key === 'tier') {
            const tA = TIER_SORT_WEIGHT[a.tier] || 0;
            const tB = TIER_SORT_WEIGHT[b.tier] || 0;
            return (tA - tB) * mult;
        }
        if (key === 'name') {
            return (a.name || '').localeCompare(b.name || '') * mult;
        }
        if (key === 'lane') {
            return (a.lane || '').localeCompare(b.lane || '') * mult;
        }
        if (key === 'winrate') {
            return ((a.winrate || 0) - (b.winrate || 0)) * mult;
        }
        if (key === 'pickrate') {
            return ((a.pickrate || 0) - (b.pickrate || 0)) * mult;
        }
        if (key === 'banrate') {
            return ((a.banrate || 0) - (b.banrate || 0)) * mult;
        }
        return 0;
    });
}

function updateSortHeaders() {
    const thList = document.querySelectorAll('th[data-sort]');
    thList.forEach(th => {
        const key = th.getAttribute('data-sort');
        const icon = th.querySelector('.sort-icon');
        if (key === currentSortKey) {
            th.classList.add('sort-active');
            if (icon) {
                icon.innerText = currentSortDirection === 'asc' ? '▲' : '▼';
            }
        } else {
            th.classList.remove('sort-active');
            if (icon) {
                icon.innerText = '⇅';
            }
        }
    });
}

function renderTierlistTable() {
    if (!currentTierlistData || !currentTierlistData.champions) return;
    const tbody = document.getElementById('tierTableBody');
    if (!tbody) return;

    updateSortHeaders();

    const sortedChamps = sortChampions(currentTierlistData.champions, currentSortKey, currentSortDirection);

    let rowsHtml = '';
    sortedChamps.forEach(c => {
        const deltaSign = c.delta >= 0 ? '+' : '';
        const deltaColor = c.delta >= 0 ? 'wr-green' : 'wr-red';
        const tierClass = `tier-${(c.tier || 'B').replace('+', '-plus')}`;
        const slug = (c.name || '').toLowerCase().replace(/[^a-z0-9]/g, '');
        const avatarUrl = `https://cdn5.lolalytics.com/champx46/${slug}.webp`;

        rowsHtml += `
            <tr onclick="switchToBuild('${c.name.replace(/'/g, "\\'")}')">
                <td style="font-weight: 700; color: #94a3b8;">${c.rank != null ? c.rank : '-'}</td>
                <td><span class="tier-badge ${tierClass}">${c.tier}</span></td>
                <td>
                    <div class="champ-cell">
                        <img class="champ-avatar" src="${avatarUrl}" onerror="this.style.display='none'">
                        <span>${c.name}</span>
                    </div>
                </td>
                <td style="text-transform: capitalize; color: #94a3b8;">${c.lane}</td>
                <td>
                    <span class="${deltaColor}">${c.winrate}%</span>
                    <span class="wr-delta">(${deltaSign}${c.delta}%)</span>
                </td>
                <td>${c.pickrate}%</td>
                <td>${c.banrate}%</td>
            </tr>
        `;
    });

    tbody.innerHTML = rowsHtml;
}

function loadTierlist(lane) {
    const tbody = document.getElementById('tierTableBody');
    tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; padding: 30px; color: #64748b;">Cargando campeones en ${lane.toUpperCase()}...</td></tr>`;

    if (!window.pywebview || !window.pywebview.api) return;

    window.pywebview.api.get_tierlist(lane).then(data => {
        if (!data || !data.champions) return;

        currentTierlistData = data;
        document.getElementById('patchPill').innerText = `Parche ${data.patch} • Media Esmeralda+: ${data.average_winrate}% • (${data.champions.length} Campeones)`;

        renderTierlistTable();
    }).catch(err => {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: #ef4444;">Error al cargar: ${err}</td></tr>`;
    });
}

// Cambiar a la pestaña de builds desde la tabla
function switchToBuild(champName) {
    document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));

    document.querySelector('[data-tab="build-tab"]').classList.add('active');
    document.getElementById('build-tab').classList.add('active');

    document.getElementById('champSearchInput').value = champName;
    loadBuild(champName);
}

// 2. Cargar Build de un Campeon
function loadBuild(champName) {
    document.getElementById('buildEmptyState').style.display = 'block';
    document.getElementById('buildEmptyState').innerHTML = `<h3>Buscando build óptima para ${champName}...</h3>`;
    document.getElementById('buildContent').style.display = 'none';

    if (!window.pywebview || !window.pywebview.api) return;

    window.pywebview.api.get_champion_build(champName).then(data => {
        if (!data || !data.most_popular) return;

        const pop = data.most_popular;
        currentLoadedBuild = {
            champion: data.champion,
            runes: pop.runes
        };

        document.getElementById('buildEmptyState').style.display = 'none';
        document.getElementById('buildContent').style.display = 'block';

        document.getElementById('buildChampTitle').innerText = `${data.champion} - Runas Óptimas`;
        document.getElementById('buildWinrateBadge').innerText = `${pop.winrate}% WR (${pop.games.toLocaleString()} partidas)`;
        document.getElementById('buildGamesCount').innerText = `${pop.type}`;

        // Rama principal
        document.getElementById('priStyleTitle').innerText = `Rama Principal: ${pop.runes.primary_style_name}`;
        document.getElementById('priRunesList').innerHTML = pop.runes.primary_runes.map(r => `<span class="rune-pill">${r.name}</span>`).join('');

        // Rama secundaria
        document.getElementById('secStyleTitle').innerText = `Rama Secundaria: ${pop.runes.sub_style_name}`;
        document.getElementById('secRunesList').innerHTML = pop.runes.secondary_runes.map(r => `<span class="rune-pill">${r.name}</span>`).join('');

        // Shards
        document.getElementById('modRunesList').innerHTML = pop.runes.shards.map(s => `<span class="rune-pill">${s.name}</span>`).join('');

        // Hechizos y habilidades
        document.getElementById('sumsPill').innerText = `Hechizos: ${pop.summoner_spells.map(s => s.name).join(' + ')}`;
        document.getElementById('skillsPill').innerText = `Maxeo: ${pop.skills.priority}`;

        // Items
        document.getElementById('startItemsList').innerHTML = pop.items.starting.map(i => `<span class="rune-pill">${i.name}</span>`).join('');
        document.getElementById('coreItemsList').innerHTML = pop.items.core.map(i => `<span class="rune-pill" style="border-color: #2563eb;">${i.name}</span>`).join('');
    }).catch(err => {
        document.getElementById('buildEmptyState').innerHTML = `<h3 style="color: #ef4444;">Error al cargar la build</h3><p>${err}</p>`;
    });
}

// 3. Comprobar conexion con el LoL local
function checkLoLStatus() {
    if (!window.pywebview || !window.pywebview.api) return;

    window.pywebview.api.get_client_status().then(status => {
        const dot = document.getElementById('clientStatusDot');
        const text = document.getElementById('clientStatusText');

        if (status.connected) {
            dot.classList.add('connected');
            text.innerText = `${status.summoner_name} (${status.soloq_rank})`;
        } else {
            dot.classList.remove('connected');
            text.innerText = 'Cliente LoL cerrado';
        }

        // Actualizar scouting solo si cambió de fase (ej. entró a selección o a partida)
        const currentPhase = status.in_game ? 'in_game' : (status.in_champ_select ? 'champ_select' : 'idle');
        if (currentPhase !== lastScoutedPhase) {
            lastScoutedPhase = currentPhase;
            if (document.getElementById('scout-tab').classList.contains('active')) {
                refreshLobby();
            }
        }
    });
}

// 4. Refrescar Scouting de Partida (Champ Select o Pantalla de Carga / In-Game)
function refreshLobby(force = false) {
    const alertBox = document.getElementById('scoutPhaseAlert');
    const emptyState = document.getElementById('scoutEmptyState');
    const activeContent = document.getElementById('scoutActiveContent');
    const alliesContainer = document.getElementById('alliesCardsContainer');
    const enemiesSection = document.getElementById('enemiesSection');
    const enemiesContainer = document.getElementById('enemiesCardsContainer');
    const subtitle = document.getElementById('scoutPhaseSubtitle');
    const balanceContainer = document.getElementById('teamBalanceContainer');
    const matchupBanner = document.getElementById('directMatchupBanner');
    const counterBanner = document.getElementById('counterSuggestionsBanner');

    if (!window.pywebview || !window.pywebview.api) return;

    window.pywebview.api.get_lobby_scout(force).then(data => {
        if (!data || data.status === 'idle' || data.status === 'disconnected') {
            emptyState.style.display = 'block';
            activeContent.style.display = 'none';
            alertBox.style.display = 'none';
            if (balanceContainer) balanceContainer.style.display = 'none';
            if (matchupBanner) matchupBanner.style.display = 'none';
            if (counterBanner) counterBanner.style.display = 'none';
            subtitle.innerText = 'Esperando partida (Selección de Campeones o Pantalla de Carga)...';
            return;
        }

        emptyState.style.display = 'none';
        activeContent.style.display = 'block';

        // Renderizar Balance de Equipos y Predicción de Victoria
        if (data.team_balance && balanceContainer) {
            renderTeamBalance(data.team_balance, balanceContainer);
        } else if (balanceContainer) {
            balanceContainer.style.display = 'none';
        }

        // Renderizar banner de matchup directo si existe
        if (data.direct_matchup && matchupBanner) {
            const m = data.direct_matchup;
            const diffClass = `diff-${m.diff_level}`;
            const wrColor = m.winrate >= 50 ? '#22c55e' : '#ef4444';
            const mySlug = m.my_champion.toLowerCase().replace(/[^a-z0-9]/g, '');
            const enemySlug = m.enemy_champion.toLowerCase().replace(/[^a-z0-9]/g, '');

            let counterItemsHtml = '';
            if (m.counter_items && m.counter_items.length > 0) {
                counterItemsHtml = `
                    <div style="margin-top: 10px;">
                        <span style="font-size: 11px; font-weight: 700; color: #38bdf8; text-transform: uppercase;">🛡️ Objetos Counter Recomendados:</span>
                        <div style="display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px;">
                            ${m.counter_items.map(it => `<span class="rune-pill" style="border-color: #38bdf8; font-size: 11px;">${it}</span>`).join('')}
                        </div>
                    </div>
                `;
            }

            let counterNotesHtml = '';
            if (m.counter_notes && m.counter_notes.length > 0) {
                counterNotesHtml = `
                    <div style="margin-top: 8px; font-size: 12px; color: #94a3b8;">
                        ${m.counter_notes.map(n => `<div>• ${n}</div>`).join('')}
                    </div>
                `;
            }

            matchupBanner.style.display = 'block';
            matchupBanner.innerHTML = `
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                    <span style="font-weight: 800; font-size: 14px; color: #fff;">🥊 ENFRENTAMIENTO DIRECTO EN LÍNEA:</span>
                    <span class="diff-badge ${diffClass}">${m.difficulty}</span>
                </div>
                <div style="display: flex; align-items: center; justify-content: space-between; font-size: 15px; font-weight: 700; margin-bottom: 12px;">
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <img src="https://cdn5.lolalytics.com/champx46/${mySlug}.webp" style="width: 32px; height: 32px; border-radius: 6px;" onerror="this.style.display='none'">
                        <span style="color: #38bdf8;">${m.my_champion}</span>
                    </div>
                    <span style="font-size: 13px; color: #64748b;">VS</span>
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <span style="color: #f43f5e;">${m.enemy_champion}</span>
                        <img src="https://cdn5.lolalytics.com/champx46/${enemySlug}.webp" style="width: 32px; height: 32px; border-radius: 6px;" onerror="this.style.display='none'">
                    </div>
                    <span style="color: ${wrColor}; font-size: 14px; margin-left: 16px;">${m.winrate}% Winrate (${m.games.toLocaleString()} partidas)</span>
                </div>
                <div class="matchup-tip-box">
                    <strong>💡 Consejo Táctico:</strong> ${m.tip}
                    ${counterItemsHtml}
                    ${counterNotesHtml}
                </div>
            `;
        } else if (matchupBanner) {
            matchupBanner.style.display = 'none';
        }

        // Renderizar banner de sugerencias de counter en Champ Select si el enemigo eligió antes
        if (data.counter_suggestions && counterBanner) {
            const cs = data.counter_suggestions;
            const enemySlug = cs.enemy_champion.toLowerCase().replace(/[^a-z0-9]/g, '');
            counterBanner.style.display = 'block';
            counterBanner.innerHTML = `
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <img src="https://cdn5.lolalytics.com/champx46/${enemySlug}.webp" style="width: 28px; height: 28px; border-radius: 6px;">
                        <span style="font-weight: 800; font-size: 13px; color: #e2e8f0;">Rival eligió a <strong style="color: #f43f5e;">${cs.enemy_champion}</strong>. ¡Counters recomendados para ganar la línea!</span>
                    </div>
                    <span style="font-size: 11px; color: #818cf8; font-weight: 600;">Lolalytics Meta</span>
                </div>
                <div style="display: flex; flex-wrap: wrap; gap: 10px; margin-top: 8px;">
                    ${cs.counters.map(c => `
                        <div class="counter-card-item" style="padding: 6px 12px; flex: 1 1 auto; max-width: 220px;" onclick="switchToBuild('${c.name.replace(/'/g, "\\'")}')">
                            <div class="counter-item-info">
                                <img src="${c.avatar_url}" style="width: 26px; height: 26px; border-radius: 6px;">
                                <strong style="font-size: 12px; color: #fff;">${c.name}</strong>
                            </div>
                            <span style="color: #22c55e; font-weight: 700; font-size: 12px;">${c.winrate}%</span>
                        </div>
                    `).join('')}
                </div>
            `;
        } else if (counterBanner) {
            counterBanner.style.display = 'none';
        }

        if (data.status === 'in_game') {
            subtitle.innerText = `🟢 ${data.phase_name} • 10 Jugadores Revelados sin censura`;
            alertBox.style.display = 'none';
            enemiesSection.style.display = 'block';
        } else if (data.status === 'champ_select') {
            subtitle.innerText = `🟡 ${data.phase_name}`;
            enemiesSection.style.display = (data.enemies && data.enemies.length > 0) ? 'block' : 'none';
            if (data.has_anonymous) {
                alertBox.style.display = 'block';
                alertBox.innerHTML = `<strong>ℹ️ Modo Anónimo de Riot (SoloQ Draft):</strong> Riot oculta los nombres en el lobby. En cuanto arranque la <strong>Pantalla de Carga</strong>, los 10 jugadores (aliados y rivales) aparecerán aquí automáticamente con el análisis completo.`;
            } else {
                alertBox.style.display = 'none';
            }
        }

        const renderPlayerCard = (p) => {
            const isMeClass = p.is_me ? 'is-me' : '';
            const rankStr = p.rank.tier !== 'UNRANKED' && p.rank.tier !== 'ANONIMO' ? `${p.rank.tier} ${p.rank.division} (${p.rank.lp} LP)` : p.rank.tier;
            const wrStr = p.rank.tier !== 'UNRANKED' && p.rank.tier !== 'ANONIMO' ? `${p.rank.winrate}% WR` : '';
            const champStr = p.champion_name ? `<span style="color: #f1f5f9; font-weight: 700;">${p.champion_name}</span>` : 'Eligiendo...';

            let badgesHtml = '';
            (p.badges || []).forEach(b => {
                let badgeClass = 'badge-info';
                if (b.includes('RACHA') || b.includes('ALTO')) badgeClass = 'badge-streak';
                if (b.includes('TILT') || b.includes('MUERE')) badgeClass = 'badge-tilt';
                badgesHtml += `<div class="badge-pill ${badgeClass}">${b}</div>`;
            });

            return `
                <div class="scout-card ${isMeClass}">
                    <div class="scout-header">
                        <span class="player-name">${p.name} ${p.is_me ? '(TU)' : ''}</span>
                        <span class="player-role">${p.assigned_position || 'FILL'}</span>
                    </div>

                    <div style="font-size: 13px; color: #cbd5e1; margin-top: 2px;">
                        ${champStr}
                    </div>

                    <div class="player-rank">${rankStr}</div>

                    <div class="scout-stats">
                        <span>Ranked: ${wrStr || 'Sin datos'}</span>
                        <span>Racha: ${p.streak}</span>
                    </div>

                    <div style="font-size: 11px; color: #94a3b8;">
                        <strong>Champs:</strong> ${p.top_champions.join(', ') || 'Sin datos'}
                    </div>

                    <div class="badges-container">
                        ${badgesHtml}
                    </div>
                </div>
            `;
        };

        alliesContainer.innerHTML = (data.allies || []).map(renderPlayerCard).join('');
        if (data.enemies && data.enemies.length > 0) {
            enemiesContainer.innerHTML = (data.enemies || []).map(renderPlayerCard).join('');
        }
    });
}

function renderTeamBalance(tb, container) {
    if (!tb) {
        container.style.display = 'none';
        return;
    }

    container.style.display = 'block';

    const allyProb = tb.ally_win_prob || 50;
    const enemyProb = tb.enemy_win_prob || 50;
    const allyDmg = tb.allies_stats?.damage_profile || { ad_pct: 50, ap_pct: 50, tank_pct: 0, summary: 'N/A' };
    const enemyDmg = tb.enemies_stats?.damage_profile || { ad_pct: 50, ap_pct: 50, tank_pct: 0, summary: 'N/A' };

    let enemyAlertHtml = '';
    if (enemyDmg.alert) {
        enemyAlertHtml = `<div class="tb-alert-badge">${enemyDmg.alert}</div>`;
    }

    const key = tb.key_players || {};

    container.innerHTML = `
        <div class="team-balance-card">
            <!-- Header con Probabilidad de Victoria -->
            <div class="tb-header">
                <div class="tb-team-badge">
                    <span style="font-size: 24px;">🔵</span>
                    <div>
                        <div class="tb-team-name blue">Tu Equipo (Aliados)</div>
                        <div class="tb-win-prob blue">${allyProb}% <span style="font-size: 13px; font-weight: 600; color: #94a3b8;">Prob. Victoria</span></div>
                    </div>
                </div>

                <div class="tb-vs-badge">
                    <span>⚖️</span>
                    <span>BALANCE DE PARTIDA</span>
                </div>

                <div class="tb-team-badge" style="text-align: right; flex-direction: row-reverse;">
                    <span style="font-size: 24px;">🔴</span>
                    <div>
                        <div class="tb-team-name red">Equipo Rival</div>
                        <div class="tb-win-prob red">${enemyProb}% <span style="font-size: 13px; font-weight: 600; color: #94a3b8;">Prob. Victoria</span></div>
                    </div>
                </div>
            </div>

            <!-- Barra Progresiva Dual -->
            <div class="tb-bar-container">
                <div class="tb-bar-blue" style="width: ${allyProb}%;"></div>
                <div class="tb-bar-red" style="width: ${enemyProb}%;"></div>
                <div class="tb-bar-indicator" style="left: ${allyProb}%;"></div>
            </div>

            <!-- Veredicto Táctico -->
            <div class="tb-verdict-box ${tb.verdict_type || 'balanced'}">
                <div class="tb-verdict-title">${tb.verdict_title}</div>
                <div class="tb-verdict-desc">${tb.verdict_desc}</div>
            </div>

            <!-- 3 Columnas Comparativas -->
            <div class="tb-grid">
                <!-- Columna 1: Estadísticas Colectivas -->
                <div class="tb-card">
                    <div class="tb-card-title">📊 Rendimiento Colectivo</div>
                    <div class="tb-stat-row">
                        <span class="tb-stat-label">Winrate Promedio</span>
                        <div class="tb-stat-val-group">
                            <span style="color: #38bdf8;">${tb.allies_stats?.avg_winrate || 50}%</span>
                            <span style="color: #64748b;">vs</span>
                            <span style="color: #f43f5e;">${tb.enemies_stats?.avg_winrate || 50}%</span>
                        </div>
                    </div>
                    <div class="tb-stat-row">
                        <span class="tb-stat-label">Tier / Elo Medio</span>
                        <div class="tb-stat-val-group">
                            <span style="color: #38bdf8;">${tb.allies_stats?.avg_tier || 'N/A'}</span>
                            <span style="color: #64748b;">vs</span>
                            <span style="color: #f43f5e;">${tb.enemies_stats?.avg_tier || 'N/A'}</span>
                        </div>
                    </div>
                    <div class="tb-stat-row">
                        <span class="tb-stat-label">KDA Promedio</span>
                        <div class="tb-stat-val-group">
                            <span style="color: #38bdf8;">${tb.allies_stats?.avg_kda || 2.0}:1</span>
                            <span style="color: #64748b;">vs</span>
                            <span style="color: #f43f5e;">${tb.enemies_stats?.avg_kda || 2.0}:1</span>
                        </div>
                    </div>
                    <div class="tb-stat-row">
                        <span class="tb-stat-label">Rachas Positivas</span>
                        <div class="tb-stat-val-group">
                            <span style="color: #22c55e;">🔥 ${tb.allies_stats?.streaks_win || 0}</span>
                            <span style="color: #64748b;">vs</span>
                            <span style="color: #f43f5e;">🔥 ${tb.enemies_stats?.streaks_win || 0}</span>
                        </div>
                    </div>
                </div>

                <!-- Columna 2: Perfil de Daño y Composición -->
                <div class="tb-card">
                    <div class="tb-card-title">🛡️ Perfil y Balance de Daño</div>
                    <div style="font-size: 11px; color: #94a3b8; display: flex; justify-content: space-between; margin-top: 2px;">
                        <span>Aliados: ${allyDmg.summary}</span>
                        <span style="color: #38bdf8; font-weight: 700;">${allyDmg.ad_pct}% AD / ${allyDmg.ap_pct}% AP</span>
                    </div>
                    <div class="tb-dmg-bar">
                        <div class="tb-dmg-ad" style="width: ${allyDmg.ad_pct}%;"></div>
                        <div class="tb-dmg-ap" style="width: ${allyDmg.ap_pct}%;"></div>
                        <div class="tb-dmg-tank" style="width: ${allyDmg.tank_pct}%;"></div>
                    </div>

                    <div style="font-size: 11px; color: #94a3b8; display: flex; justify-content: space-between; margin-top: 6px;">
                        <span>Rivales: ${enemyDmg.summary}</span>
                        <span style="color: #f43f5e; font-weight: 700;">${enemyDmg.ad_pct}% AD / ${enemyDmg.ap_pct}% AP</span>
                    </div>
                    <div class="tb-dmg-bar">
                        <div class="tb-dmg-ad" style="width: ${enemyDmg.ad_pct}%;"></div>
                        <div class="tb-dmg-ap" style="width: ${enemyDmg.ap_pct}%;"></div>
                        <div class="tb-dmg-tank" style="width: ${enemyDmg.tank_pct}%;"></div>
                    </div>

                    ${enemyAlertHtml}
                </div>

                <!-- Columna 3: Focos Tácticos Clave -->
                <div class="tb-card">
                    <div class="tb-card-title">🎯 Focos y Objetivos Clave</div>
                    ${key.ally_mvp ? `
                        <div class="tb-key-item">
                            <div class="tb-key-title">
                                <span style="color: #38bdf8;">👑 ${key.ally_mvp.champion} (${key.ally_mvp.name})</span>
                                <span class="tb-key-role" style="color: #38bdf8;">${key.ally_mvp.role}</span>
                            </div>
                            <div class="tb-key-sub">Tu Mejor Apuesta: ${key.ally_mvp.reason}</div>
                        </div>
                    ` : ''}

                    ${key.enemy_threat ? `
                        <div class="tb-key-item" style="border-color: rgba(244, 63, 94, 0.4);">
                            <div class="tb-key-title">
                                <span style="color: #f43f5e;">⚠️ ${key.enemy_threat.champion} (${key.enemy_threat.name})</span>
                                <span class="tb-key-role" style="color: #f43f5e;">${key.enemy_threat.role}</span>
                            </div>
                            <div class="tb-key-sub">Mayor Amenaza Rival: ${key.enemy_threat.reason}</div>
                        </div>
                    ` : ''}

                    ${key.enemy_weak_link ? `
                        <div class="tb-key-item" style="border-color: rgba(245, 158, 11, 0.3);">
                            <div class="tb-key-title">
                                <span style="color: #f59e0b;">🎯 ${key.enemy_weak_link.champion} (${key.enemy_weak_link.name})</span>
                                <span class="tb-key-role" style="color: #f59e0b;">${key.enemy_weak_link.role}</span>
                            </div>
                            <div class="tb-key-sub">Objetivo Vulnerable: ${key.enemy_weak_link.reason}</div>
                        </div>
                    ` : ''}
                </div>
            </div>
        </div>
    `;
}

// 5. Buscador de Matchups y Counters (Pestaña Matchups)
function initMatchupSearch() {
    const mode1v1Btn = document.getElementById('mode1v1Btn');
    const modeCountersBtn = document.getElementById('modeCountersBtn');
    const section1v1 = document.getElementById('matchup1v1Section');
    const sectionCounters = document.getElementById('matchupCountersSection');

    // Cambiar de modo 1v1 vs Counters
    if (mode1v1Btn && modeCountersBtn) {
        mode1v1Btn.addEventListener('click', () => {
            mode1v1Btn.classList.add('active');
            modeCountersBtn.classList.remove('active');
            section1v1.style.display = 'block';
            sectionCounters.style.display = 'none';
        });

        modeCountersBtn.addEventListener('click', () => {
            modeCountersBtn.classList.add('active');
            mode1v1Btn.classList.remove('active');
            sectionCounters.style.display = 'block';
            section1v1.style.display = 'none';
        });
    }

    // Modo 1: Comparador 1v1
    const btn1v1 = document.getElementById('compareMatchupBtn');
    const myInput = document.getElementById('matchupMyChamp');
    const enemyInput = document.getElementById('matchupEnemyChamp');
    const emptyState1v1 = document.getElementById('matchupEmptyState');
    const resultContent1v1 = document.getElementById('matchupResultContent');

    const handleCompare1v1 = () => {
        const myChamp = myInput.value.trim();
        const enemyChamp = enemyInput.value.trim();

        if (!myChamp || !enemyChamp) {
            alert('Por favor ingresa ambos campeones para comparar.');
            return;
        }

        emptyState1v1.style.display = 'block';
        emptyState1v1.innerHTML = `<h3>Consultando estadísticas del matchup en Lolalytics...</h3>`;
        resultContent1v1.style.display = 'none';

        if (!window.pywebview || !window.pywebview.api) return;

        window.pywebview.api.get_matchup(myChamp, enemyChamp).then(m => {
            emptyState1v1.style.display = 'none';
            resultContent1v1.style.display = 'block';

            const diffClass = `diff-${m.diff_level}`;
            const wrPercent = m.winrate;
            const enemyWr = (100 - wrPercent).toFixed(2);
            const mySlug = m.my_champion.toLowerCase().replace(/[^a-z0-9]/g, '');
            const enemySlug = m.enemy_champion.toLowerCase().replace(/[^a-z0-9]/g, '');

            let counterItemsHtml = '';
            if (m.counter_items && m.counter_items.length > 0) {
                counterItemsHtml = `
                    <div style="margin-top: 14px;">
                        <span style="font-size: 12px; font-weight: 700; color: #38bdf8; text-transform: uppercase;">🛡️ Objetos Clave de Counter:</span>
                        <div style="display: flex; flex-wrap: wrap; gap: 8px; margin-top: 6px;">
                            ${m.counter_items.map(it => `<span class="rune-pill" style="border-color: #38bdf8;">${it}</span>`).join('')}
                        </div>
                    </div>
                `;
            }

            let counterNotesHtml = '';
            if (m.counter_notes && m.counter_notes.length > 0) {
                counterNotesHtml = `
                    <div style="margin-top: 10px; font-size: 13px; color: #94a3b8; line-height: 1.6;">
                        ${m.counter_notes.map(n => `<div>• ${n}</div>`).join('')}
                    </div>
                `;
            }

            resultContent1v1.innerHTML = `
                <div class="matchup-container-card">
                    <div class="matchup-header">
                        <div class="champs-comparison">
                            <div class="champ-profile">
                                <img class="champ-profile-img" src="https://cdn5.lolalytics.com/champx46/${mySlug}.webp" onerror="this.style.display='none'">
                                <div>
                                    <div style="font-size: 16px; font-weight: 800; color: #fff;">${m.my_champion}</div>
                                    <div style="font-size: 12px; color: #38bdf8; font-weight: 600;">Tu Campeón</div>
                                </div>
                            </div>
                            <span style="font-size: 18px; font-weight: 900; color: #64748b;">VS</span>
                            <div class="champ-profile">
                                <img class="champ-profile-img" src="https://cdn5.lolalytics.com/champx46/${enemySlug}.webp" onerror="this.style.display='none'">
                                <div>
                                    <div style="font-size: 16px; font-weight: 800; color: #fff;">${m.enemy_champion}</div>
                                    <div style="font-size: 12px; color: #f43f5e; font-weight: 600;">Rival</div>
                                </div>
                            </div>
                        </div>

                        <div class="diff-badge ${diffClass}">${m.difficulty}</div>
                    </div>

                    <div class="matchup-wr-bar-container">
                        <div class="matchup-wr-labels">
                            <span style="color: #22c55e;">${m.my_champion}: ${wrPercent}%</span>
                            <span style="color: #94a3b8; font-size: 11px;">${m.games.toLocaleString()} partidas analizadas</span>
                            <span style="color: #ef4444;">${m.enemy_champion}: ${enemyWr}%</span>
                        </div>
                        <div class="wr-progress-bar">
                            <div class="wr-progress-fill" style="width: ${wrPercent}%;"></div>
                        </div>
                    </div>

                    <div class="matchup-tip-box" style="margin-top: 18px;">
                        <h4 style="font-size: 13px; font-weight: 700; color: #fff; margin-bottom: 4px;">💡 Recomendación Estratégica:</h4>
                        <p>${m.tip}</p>
                        ${counterItemsHtml}
                        ${counterNotesHtml}
                    </div>
                </div>
            `;
        }).catch(err => {
            emptyState1v1.style.display = 'block';
            emptyState1v1.innerHTML = `<h3 style="color: #ef4444;">Error al consultar el matchup</h3><p>${err}</p>`;
        });
    };

    if (btn1v1) {
        btn1v1.addEventListener('click', handleCompare1v1);
        [myInput, enemyInput].forEach(inp => inp.addEventListener('keydown', e => {
            if (e.key === 'Enter') handleCompare1v1();
        }));
    }

    // Modo 2: Explorador de Counters
    const btnCounters = document.getElementById('searchCountersBtn');
    const inputCounters = document.getElementById('countersChampInput');
    const emptyStateCounters = document.getElementById('countersEmptyState');
    const resultContentCounters = document.getElementById('countersResultContent');

    const handleSearchCounters = () => {
        const champ = inputCounters.value.trim();
        if (!champ) {
            alert('Por favor ingresa un campeón para buscar sus counters.');
            return;
        }

        emptyStateCounters.style.display = 'block';
        emptyStateCounters.innerHTML = `<h3>Obteniendo mejores y peores enfrentamientos de ${champ} en Lolalytics...</h3>`;
        resultContentCounters.style.display = 'none';

        if (!window.pywebview || !window.pywebview.api) return;

        window.pywebview.api.get_champion_counters(champ).then(data => {
            if (!data) return;
            emptyStateCounters.style.display = 'none';
            resultContentCounters.style.display = 'block';

            const worstHtml = (data.worst || []).map(c => `
                <div class="counter-card-item" onclick="directCompareFromCounter('${data.champion}', '${c.name}')">
                    <div class="counter-item-info">
                        <img class="counter-avatar" src="${c.avatar_url}" onerror="this.style.display='none'">
                        <div>
                            <div style="font-weight: 700; color: #fff; font-size: 13px;">${c.name}</div>
                            <div style="font-size: 11px; color: #94a3b8;">${c.games.toLocaleString()} partidas</div>
                        </div>
                    </div>
                    <div class="counter-item-stats">
                        <div style="color: #ef4444; font-weight: 800; font-size: 14px;">${c.winrate}% WR</div>
                        <div style="font-size: 11px; color: #f87171;">Counter Fuerte</div>
                    </div>
                </div>
            `).join('');

            const bestHtml = (data.best || []).map(c => `
                <div class="counter-card-item" onclick="directCompareFromCounter('${data.champion}', '${c.name}')">
                    <div class="counter-item-info">
                        <img class="counter-avatar" src="${c.avatar_url}" onerror="this.style.display='none'">
                        <div>
                            <div style="font-weight: 700; color: #fff; font-size: 13px;">${c.name}</div>
                            <div style="font-size: 11px; color: #94a3b8;">${c.games.toLocaleString()} partidas</div>
                        </div>
                    </div>
                    <div class="counter-item-stats">
                        <div style="color: #22c55e; font-weight: 800; font-size: 14px;">${c.winrate}% WR</div>
                        <div style="font-size: 11px; color: #4ade80;">Presa Fácil</div>
                    </div>
                </div>
            `).join('');

            resultContentCounters.innerHTML = `
                <div class="counters-grid">
                    <div class="counter-column">
                        <div class="counter-col-header">
                            <div>
                                <h3 style="font-size: 14px; font-weight: 800; color: #ef4444;">🔴 PEORES ENFRENTAMIENTOS</h3>
                                <p style="font-size: 11px; color: #94a3b8;">Campeones que más vencen a ${data.champion}</p>
                            </div>
                            <span class="rune-pill" style="border-color: #ef4444; color: #ef4444;">Counters</span>
                        </div>
                        <div class="counter-list">
                            ${worstHtml || '<div style="color: #64748b; padding: 20px;">Sin datos suficientes</div>'}
                        </div>
                    </div>

                    <div class="counter-column">
                        <div class="counter-col-header">
                            <div>
                                <h3 style="font-size: 14px; font-weight: 800; color: #22c55e;">🟢 MEJORES ENFRENTAMIENTOS</h3>
                                <p style="font-size: 11px; color: #94a3b8;">Campeones que ${data.champion} más destruye</p>
                            </div>
                            <span class="rune-pill" style="border-color: #22c55e; color: #22c55e;">Ventaja</span>
                        </div>
                        <div class="counter-list">
                            ${bestHtml || '<div style="color: #64748b; padding: 20px;">Sin datos suficientes</div>'}
                        </div>
                    </div>
                </div>
            `;
        }).catch(err => {
            emptyStateCounters.style.display = 'block';
            emptyStateCounters.innerHTML = `<h3 style="color: #ef4444;">Error al cargar counters</h3><p>${err}</p>`;
        });
    };

    if (btnCounters) {
        btnCounters.addEventListener('click', handleSearchCounters);
        inputCounters.addEventListener('keydown', e => {
            if (e.key === 'Enter') handleSearchCounters();
        });
    }
}

// Utilidad para cambiar directamente a la comparación 1v1 desde un counter
function directCompareFromCounter(myChamp, enemyChamp) {
    document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));

    const matchupNav = document.querySelector('[data-tab="matchup-tab"]');
    if (matchupNav) matchupNav.classList.add('active');
    document.getElementById('matchup-tab').classList.add('active');

    const mode1v1Btn = document.getElementById('mode1v1Btn');
    if (mode1v1Btn) mode1v1Btn.click();

    const myInput = document.getElementById('matchupMyChamp');
    const enemyInput = document.getElementById('matchupEnemyChamp');
    const compareBtn = document.getElementById('compareMatchupBtn');

    if (myInput && enemyInput && compareBtn) {
        myInput.value = myChamp;
        enemyInput.value = enemyChamp;
        compareBtn.click();
    }
}

// ========================================================
// 6. GESTOR DE MI PERFIL E HISTORIAL (ESTILO OP.GG)
// ========================================================
let cachedProfileData = null;
let currentProfileFilter = 'all';

function initProfile() {
    const refreshBtn = document.getElementById('refreshProfileBtn');
    const retryBtn = document.getElementById('retryProfileBtn');
    if (refreshBtn) refreshBtn.addEventListener('click', () => loadUserProfile());
    if (retryBtn) retryBtn.addEventListener('click', () => loadUserProfile());

    const filterBtns = document.querySelectorAll('.profile-filter-btn');
    filterBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            filterBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentProfileFilter = btn.getAttribute('data-filter');
            if (cachedProfileData && cachedProfileData.matches) {
                renderMatchesList(cachedProfileData.matches, cachedProfileData.ddragon_version);
            }
        });
    });
}

function loadUserProfile() {
    const emptyState = document.getElementById('profileEmptyState');
    const mainContent = document.getElementById('profileMainContent');
    const sumNameEl = document.getElementById('profileSummonerName');

    if (!window.pywebview || !window.pywebview.api || !window.pywebview.api.get_user_profile) return;

    if (sumNameEl && (!cachedProfileData || !cachedProfileData.summoner)) {
        sumNameEl.innerText = 'Cargando perfil e historial...';
    }

    window.pywebview.api.get_user_profile().then(data => {
        if (!data || data.status !== 'connected') {
            if (emptyState) emptyState.style.display = 'block';
            if (mainContent) mainContent.style.display = 'none';
            if (sumNameEl) sumNameEl.innerText = 'Cliente no conectado';
            return;
        }

        cachedProfileData = data;
        if (emptyState) emptyState.style.display = 'none';
        if (mainContent) mainContent.style.display = 'grid';

        renderProfileData(data);
        loadPostGameAutopsy();
    }).catch(err => {
        console.error("[!] Error cargando perfil:", err);
        if (emptyState) emptyState.style.display = 'block';
        if (mainContent) mainContent.style.display = 'none';
    });
}

function renderProfileData(data) {
    const ddragonVer = data.ddragon_version || '14.21.1';

    // 1. Header del Invocador
    const avatarEl = document.getElementById('profileAvatar');
    const nameEl = document.getElementById('profileSummonerName');
    const levelEl = document.getElementById('profileLevel');

    if (avatarEl && data.summoner.icon_url) avatarEl.src = data.summoner.icon_url;
    if (nameEl) nameEl.innerText = data.summoner.name || 'Invocador';
    if (levelEl) levelEl.innerText = `Nv. ${data.summoner.level || 1}`;

    // 2. Tarjetas de Rango (SoloQ y Flex)
    const solo = data.ranked?.soloq || { tier: 'UNRANKED', division: '', lp: 0, winrate: 0, wins: 0, losses: 0 };
    const flex = data.ranked?.flex || { tier: 'UNRANKED', division: '', lp: 0, winrate: 0, wins: 0, losses: 0 };

    const soloqTierEl = document.getElementById('profileSoloqTier');
    const soloqLpEl = document.getElementById('profileSoloqLp');
    const soloqWrEl = document.getElementById('profileSoloqWr');
    if (soloqTierEl) soloqTierEl.innerText = solo.tier !== 'UNRANKED' ? `${solo.tier} ${solo.division}` : 'UNRANKED';
    if (soloqLpEl) soloqLpEl.innerText = solo.tier !== 'UNRANKED' ? `${solo.lp} LP` : 'Sin clasificar';
    if (soloqWrEl) soloqWrEl.innerText = (solo.wins + solo.losses > 0) ? `${solo.winrate}% WR (${solo.wins}V ${solo.losses}D)` : '--';

    const flexTierEl = document.getElementById('profileFlexTier');
    const flexLpEl = document.getElementById('profileFlexLp');
    const flexWrEl = document.getElementById('profileFlexWr');
    if (flexTierEl) flexTierEl.innerText = flex.tier !== 'UNRANKED' ? `${flex.tier} ${flex.division}` : 'UNRANKED';
    if (flexLpEl) flexLpEl.innerText = flex.tier !== 'UNRANKED' ? `${flex.lp} LP` : 'Sin clasificar';
    if (flexWrEl) flexWrEl.innerText = (flex.wins + flex.losses > 0) ? `${flex.winrate}% WR (${flex.wins}V ${flex.losses}D)` : '--';

    // 3. Campeones Más Jugados de la Temporada
    const mostPlayedContainer = document.getElementById('profileMostPlayedList');
    if (mostPlayedContainer) {
        if (!data.most_played_champions || data.most_played_champions.length === 0) {
            mostPlayedContainer.innerHTML = '<div style="font-size: 12px; color: #94a3b8; padding: 8px 0;">No hay partidas registradas aún.</div>';
        } else {
            mostPlayedContainer.innerHTML = data.most_played_champions.slice(0, 7).map(c => {
                const wrColor = c.winrate >= 50 ? '#22c55e' : '#ef4444';
                const kdaColor = c.kda_ratio >= 3.0 ? '#22c55e' : (c.kda_ratio >= 2.0 ? '#38bdf8' : '#94a3b8');
                return `
                    <div class="most-played-item" style="cursor: pointer;" onclick="switchToBuild('${c.champion_name.replace(/'/g, "\\'")}')">
                        <div class="most-played-left">
                            <img class="most-played-avatar" src="https://cdn5.lolalytics.com/champx46/${c.champion_slug}.webp" onerror="this.style.display='none'">
                            <div>
                                <div class="most-played-name">${c.champion_name}</div>
                                <div class="most-played-cs">CS ${c.avg_cs} • ${c.games} ${c.games === 1 ? 'partida' : 'partidas'}</div>
                            </div>
                        </div>
                        <div class="most-played-right">
                            <div class="most-played-kda" style="color: ${kdaColor};">${c.kda_ratio}:1 KDA</div>
                            <div class="most-played-wr" style="color: ${wrColor};">${c.winrate}% (${c.wins}V/${c.losses}D)</div>
                        </div>
                    </div>
                `;
            }).join('');
        }
    }

    // 4. Resumen Superior de Rendimiento Reciente (Donut + Stats + Roles)
    const summaryContainer = document.getElementById('profileRecentSummary');
    if (summaryContainer && data.recent_summary) {
        const sum = data.recent_summary;
        const donutWr = sum.winrate || 0;
        const kdaColor = sum.kda_ratio >= 3.0 ? '#22c55e' : (sum.kda_ratio >= 2.0 ? '#38bdf8' : '#94a3b8');

        let recentChampsHtml = '';
        if (sum.recent_champions && sum.recent_champions.length > 0) {
            recentChampsHtml = sum.recent_champions.map(rc => `
                <div class="summary-champ-row">
                    <div class="summary-champ-left">
                        <img src="https://cdn5.lolalytics.com/champx46/${rc.champion_slug}.webp" onerror="this.style.display='none'">
                        <strong style="color: #fff; font-size: 11px;">${rc.champion_name}</strong>
                    </div>
                    <div style="font-size: 11px;">
                        <span style="color: ${rc.winrate >= 50 ? '#22c55e' : '#ef4444'}; font-weight: 700;">${rc.winrate}%</span>
                        <span style="color: #64748b; margin-left: 4px;">(${rc.wins}V/${rc.losses}D)</span>
                        <span style="color: #38bdf8; margin-left: 6px; font-weight: 700;">${rc.kda_ratio}:1</span>
                    </div>
                </div>
            `).join('');
        } else {
            recentChampsHtml = '<span style="font-size: 11px; color: #94a3b8;">Sin datos recientes</span>';
        }

        const roles = sum.role_distribution || { top: 0, jungle: 0, mid: 0, adc: 0, support: 0 };

        summaryContainer.innerHTML = `
            <!-- Donut Winrate -->
            <div class="summary-donut-col">
                <div class="summary-donut-circle" style="background: conic-gradient(#2563eb 0% ${donutWr}%, #f43f5e ${donutWr}% 100%);">
                    <div class="summary-donut-inner">${donutWr}%</div>
                </div>
                <div>
                    <div style="font-size: 12px; font-weight: 800; color: #f1f5f9;">${sum.total_games} Partidas</div>
                    <div style="font-size: 11px; font-weight: 700; margin-top: 2px;">
                        <span style="color: #38bdf8;">${sum.wins}V</span>
                        <span style="color: #64748b;"> - </span>
                        <span style="color: #f43f5e;">${sum.losses}D</span>
                    </div>
                </div>
            </div>

            <!-- KDA Stats -->
            <div class="summary-kda-col">
                <div class="summary-kda-numbers">${sum.avg_kills} / <span style="color: #f43f5e;">${sum.avg_deaths}</span> / ${sum.avg_assists}</div>
                <div class="summary-kda-ratio" style="color: ${kdaColor};">${sum.kda_ratio}:1 KDA</div>
                <div class="summary-pkill">P/Kill ${sum.kill_participation}%</div>
            </div>

            <!-- Top 3 Campeones Recientes -->
            <div class="summary-champs-col">
                <div style="font-size: 10px; font-weight: 800; color: #94a3b8; text-transform: uppercase;">Más Jugados (Reciente)</div>
                ${recentChampsHtml}
            </div>

            <!-- Barras de Rol Preferido -->
            <div class="summary-roles-col">
                <div style="font-size: 10px; font-weight: 800; color: #94a3b8; text-transform: uppercase;">Rol Preferido</div>
                <div class="role-bars-container">
                    <div class="role-bar-item">
                        <div class="role-bar-track" title="Top: ${roles.top}%">
                            <div class="role-bar-fill" style="height: ${Math.max(roles.top, 5)}%;"></div>
                        </div>
                        <span class="role-bar-label">TOP</span>
                    </div>
                    <div class="role-bar-item">
                        <div class="role-bar-track" title="Jungle: ${roles.jungle}%">
                            <div class="role-bar-fill" style="height: ${Math.max(roles.jungle, 5)}%;"></div>
                        </div>
                        <span class="role-bar-label">JUG</span>
                    </div>
                    <div class="role-bar-item">
                        <div class="role-bar-track" title="Mid: ${roles.mid}%">
                            <div class="role-bar-fill" style="height: ${Math.max(roles.mid, 5)}%;"></div>
                        </div>
                        <span class="role-bar-label">MID</span>
                    </div>
                    <div class="role-bar-item">
                        <div class="role-bar-track" title="ADC: ${roles.adc}%">
                            <div class="role-bar-fill" style="height: ${Math.max(roles.adc, 5)}%;"></div>
                        </div>
                        <span class="role-bar-label">ADC</span>
                    </div>
                    <div class="role-bar-item">
                        <div class="role-bar-track" title="Support: ${roles.support}%">
                            <div class="role-bar-fill" style="height: ${Math.max(roles.support, 5)}%;"></div>
                        </div>
                        <span class="role-bar-label">SUP</span>
                    </div>
                </div>
            </div>
        `;
    }

    // 5. Lista de Partidas Recientes
    renderMatchesList(data.matches || [], ddragonVer);
}

function renderMatchesList(matches, ddragonVer) {
    const listContainer = document.getElementById('profileMatchesList');
    if (!listContainer) return;

    // Filtrar partidas según botón activo
    let filtered = matches;
    if (currentProfileFilter === 'soloq') {
        filtered = matches.filter(m => (m.queue_name || '').toLowerCase().includes('solo'));
    } else if (currentProfileFilter === 'flex') {
        filtered = matches.filter(m => (m.queue_name || '').toLowerCase().includes('flex'));
    } else if (currentProfileFilter === 'normal') {
        filtered = matches.filter(m => (m.queue_name || '').toLowerCase().includes('normal'));
    } else if (currentProfileFilter === 'aram') {
        filtered = matches.filter(m => (m.queue_name || '').toLowerCase().includes('aram'));
    }

    if (!filtered || filtered.length === 0) {
        listContainer.innerHTML = '<div class="empty-state"><h3>No se encontraron partidas con este filtro</h3></div>';
        return;
    }

    listContainer.innerHTML = filtered.map(m => {
        const isWin = m.win;
        const resultClass = isWin ? 'win' : 'defeat';
        const resultText = isWin ? 'Victoria' : 'Derrota';
        const kdaColor = m.kda_ratio >= 3.0 ? '#22c55e' : (m.kda_ratio >= 2.0 ? '#38bdf8' : '#94a3b8');

        // Renderizar slots de objetos
        const itemsHtml = (m.items || []).map(itId => {
            if (itId && itId > 0) {
                return `<div class="match-item-slot" title="Objeto ${itId}"><img src="https://ddragon.leagueoflegends.com/cdn/${ddragonVer}/img/item/${itId}.png" onerror="this.style.display='none'"></div>`;
            }
            return `<div class="match-item-slot"></div>`;
        }).join('');

        // Renderizar 10 jugadores (5 aliados, 5 rivales)
        const renderMiniPlayer = (p) => {
            const isMeClass = p.is_me ? 'is-me' : '';
            return `
                <div class="match-mini-player ${isMeClass}" title="${p.name} (${p.champion_name})">
                    <img src="https://cdn5.lolalytics.com/champx46/${p.champion_slug}.webp" onerror="this.style.display='none'">
                    <span>${p.name.split('#')[0].slice(0, 8)}</span>
                </div>
            `;
        };

        const alliesMiniHtml = (m.allies || []).map(renderMiniPlayer).join('');
        const enemiesMiniHtml = (m.enemies || []).map(renderMiniPlayer).join('');

        return `
            <div class="match-card ${resultClass}">
                <!-- Info Cola y Tiempo -->
                <div class="match-info-col">
                    <span class="match-queue-name">${m.queue_name}</span>
                    <span class="match-time-ago">${m.time_ago}</span>
                    <span class="match-result-text">${resultText}</span>
                    <span class="match-duration">${m.duration_str}</span>
                </div>

                <!-- Campeón, Nivel y Hechizos -->
                <div class="match-champ-col">
                    <div class="match-avatar-wrapper" style="cursor: pointer;" onclick="switchToBuild('${m.champion_name.replace(/'/g, "\\'")}')">
                        <img class="match-avatar-img" src="https://cdn5.lolalytics.com/champx46/${m.champion_slug}.webp" onerror="this.style.display='none'">
                        <div class="match-level-badge">${m.champ_level}</div>
                    </div>
                    <div class="match-spells-col">
                        <img class="match-spell-icon" src="https://ddragon.leagueoflegends.com/cdn/${ddragonVer}/img/spell/${m.spell1_name}.png" onerror="this.style.display='none'">
                        <img class="match-spell-icon" src="https://ddragon.leagueoflegends.com/cdn/${ddragonVer}/img/spell/${m.spell2_name}.png" onerror="this.style.display='none'">
                    </div>
                    <div style="font-size: 12px; font-weight: 700; color: #f1f5f9;">${m.champion_name}</div>
                </div>

                <!-- KDA, CS y Participación -->
                <div class="match-kda-col">
                    <div class="match-kda-text">${m.kills} / <span style="color: #f43f5e;">${m.deaths}</span> / ${m.assists}</div>
                    <div class="match-kda-ratio" style="color: ${kdaColor};">${m.kda_ratio}:1 KDA</div>
                    <div class="match-cs-text">CS ${m.cs} (${m.cs_per_min})</div>
                    <div class="match-pkill-text">P/Kill ${m.kill_participation}%</div>
                </div>

                <!-- Objetos Finales -->
                <div class="match-items-grid">
                    ${itemsHtml}
                </div>

                <!-- 10 Invocadores de la Partida -->
                <div class="match-players-grid">
                    <div>${alliesMiniHtml}</div>
                    <div>${enemiesMiniHtml}</div>
                </div>
            </div>
        `;
    }).join('');
}

// ----------------------------------------------------
// 6. Autopsia Post-Partida (Medallas & Rendimiento)
// ----------------------------------------------------
function loadPostGameAutopsy(force = false) {
    if (!window.pywebview || !window.pywebview.api || !window.pywebview.api.get_postgame_autopsy) return;
    const cardEl = document.getElementById('postGameAutopsyCard');
    if (!cardEl) return;

    window.pywebview.api.get_postgame_autopsy(force).then(data => {
        if (!data || data.status !== 'ready') {
            cardEl.style.display = 'none';
            return;
        }
        renderPostGameAutopsy(data);
    }).catch(err => {
        console.error("[!] Error cargando autopsia post-partida:", err);
    });
}

function renderPostGameAutopsy(data) {
    const cardEl = document.getElementById('postGameAutopsyCard');
    const headerEl = document.getElementById('autopsyHeader');
    const verdictEl = document.getElementById('autopsyVerdict');
    const gridEl = document.getElementById('autopsyGrid');

    if (!cardEl || !headerEl || !verdictEl || !gridEl) return;

    // Ajustar borde y estilos según resultado
    cardEl.classList.remove('win-border', 'defeat-border');
    verdictEl.classList.remove('win-verdict', 'defeat-verdict');

    if (data.win) {
        cardEl.classList.add('win-border');
        verdictEl.classList.add('win-verdict');
    } else {
        cardEl.classList.add('defeat-border');
        verdictEl.classList.add('defeat-verdict');
    }

    const titleColor = data.win ? '#22c55e' : '#f43f5e';
    const kdaColor = data.kda_ratio >= 3.0 ? '#22c55e' : (data.kda_ratio >= 2.0 ? '#38bdf8' : '#94a3b8');

    // 1. Header
    headerEl.innerHTML = `
        <div class="autopsy-header-left">
            <img class="autopsy-champ-img" src="https://cdn5.lolalytics.com/champx46/${data.champion_slug}.webp" onerror="this.style.display='none'">
            <div>
                <div class="autopsy-title-tag" style="color: ${titleColor};">🔬 ${data.verdict_title}</div>
                <div class="autopsy-champ-meta">${data.champion_name} • ${data.duration_str}</div>
            </div>
        </div>
        <div class="autopsy-stats-strip">
            <div>KDA: <span class="autopsy-stat-val" style="color: ${kdaColor};">${data.kills}/${data.deaths}/${data.assists} (${data.kda_ratio}:1)</span></div>
            <div>CS: <span class="autopsy-stat-val">${data.cs} (${data.cs_per_min}/min)</span></div>
            <div>P/Kill: <span class="autopsy-stat-val" style="color: #f43f5e;">${data.kill_participation}%</span></div>
            <button class="btn-secondary" style="font-size: 11px; padding: 4px 10px;" onclick="loadPostGameAutopsy(true)" title="Forzar análisis de la partida más reciente">↻ Recalcular</button>
        </div>
    `;

    // 2. Veredicto
    verdictEl.innerHTML = `
        <strong>Diagnóstico Táctico:</strong> ${data.verdict_summary}
    `;

    // 3. Medallas / Fortalezas
    const strengthsHtml = (data.strengths && data.strengths.length > 0)
        ? data.strengths.map(s => `
            <div class="autopsy-badge-card positive">
                <div class="autopsy-badge-name" style="color: #22c55e;">
                    <span>${s.badge}</span>
                </div>
                <div class="autopsy-badge-metric">${s.title}</div>
                <div class="autopsy-badge-desc">${s.desc}</div>
            </div>
        `).join('')
        : `<div style="font-size: 11px; color: #64748b; font-style: italic; padding: 8px 0;">No se registraron medallas destacadas en esta partida.</div>`;

    // 4. Puntos Críticos / Debilidades
    const weaknessesHtml = (data.weaknesses && data.weaknesses.length > 0)
        ? data.weaknesses.map(w => `
            <div class="autopsy-badge-card negative">
                <div class="autopsy-badge-name" style="color: #f43f5e;">
                    <span>${w.badge}</span>
                </div>
                <div class="autopsy-badge-metric">${w.title}</div>
                <div class="autopsy-badge-desc">${w.desc}</div>
            </div>
        `).join('')
        : `<div style="font-size: 11px; color: #22c55e; font-style: italic; padding: 8px 0;">✨ ¡Partida limpia! No se detectaron fallos críticos individuales.</div>`;

    gridEl.innerHTML = `
        <div class="autopsy-col">
            <div class="autopsy-section-title" style="color: #22c55e;">🌟 Lo Que Hiciste Bien</div>
            <div class="autopsy-badge-list">
                ${strengthsHtml}
            </div>
        </div>
        <div class="autopsy-col">
            <div class="autopsy-section-title" style="color: #f43f5e;">⚠️ Puntos Críticos / Qué Costó la Partida</div>
            <div class="autopsy-badge-list">
                ${weaknessesHtml}
            </div>
        </div>
    `;

    cardEl.style.display = 'block';
}
