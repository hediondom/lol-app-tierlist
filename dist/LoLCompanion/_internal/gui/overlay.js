let isCompact = false;

document.addEventListener('DOMContentLoaded', () => {
    initControls();

    window.addEventListener('pywebviewready', () => {
        console.log('[Overlay] PyWebView listo.');
        updateState();
        setInterval(updateState, 2000);
    });
});

function initControls() {
    const compactBtn = document.getElementById('compactBtn');
    const closeBtn = document.getElementById('closeBtn');
    const body = document.getElementById('overlayBody');
    const container = document.getElementById('overlayContainer');

    if (compactBtn) {
        compactBtn.addEventListener('click', () => {
            isCompact = !isCompact;
            container.classList.toggle('compact', isCompact);
            body.style.display = isCompact ? 'none' : 'flex';
            compactBtn.innerText = isCompact ? '+' : '−';

            if (window.pywebview && window.pywebview.api) {
                window.pywebview.api.toggle_compact(isCompact);
            }
        });
    }

    if (closeBtn) {
        closeBtn.addEventListener('click', () => {
            if (window.pywebview && window.pywebview.api) {
                window.pywebview.api.close_overlay();
            }
        });
    }
}

function updateState() {
    if (!window.pywebview || !window.pywebview.api) return;

    window.pywebview.api.get_overlay_state().then(state => {
        if (!state) return;

        const viewInGame = document.getElementById('viewInGame');
        const viewChampSelect = document.getElementById('viewChampSelect');
        const viewIdle = document.getElementById('viewIdle');
        const headerTitle = document.getElementById('overlayHeaderTitle');
        const pulse = document.getElementById('overlayPulse');

        // Modo Partida en Vivo
        if (state.mode === 'in_game' && state.live_stats) {
            viewInGame.style.display = 'block';
            viewChampSelect.style.display = 'none';
            viewIdle.style.display = 'none';

            const ls = state.live_stats;
            headerTitle.innerText = state.title || 'En Partida';
            pulse.style.background = '#22c55e';
            pulse.style.boxShadow = '0 0 8px #22c55e';

            document.getElementById('gameTimeVal').innerText = ls.game_time_str;
            document.getElementById('kdaVal').innerText = ls.kda_str;
            document.getElementById('csVal').innerText = `${ls.cs} (${ls.cs_per_min})`;
            document.getElementById('csVal').style.color = ls.cs_color || '#38bdf8';
            document.getElementById('goldVal').innerText = `${ls.gold.toLocaleString()} G`;

            // Matchup
            const m = state.matchup;
            if (m) {
                document.getElementById('matchupCard').style.display = 'block';
                document.getElementById('myChampName').innerText = m.my_champion;
                document.getElementById('enemyChampName').innerText = m.enemy_champion;
                document.getElementById('matchupWrBadge').innerText = `${m.winrate}% WR`;
                document.getElementById('matchupWrBadge').style.color = m.winrate >= 50 ? '#22c55e' : '#ef4444';

                const diffTag = document.getElementById('overlayDiffTag');
                diffTag.className = `diff-tag diff-${m.diff_level}`;
                diffTag.innerText = m.difficulty;

                const alertBox = document.getElementById('counterAlertBox');
                if (m.counter_items && m.counter_items.length > 0) {
                    alertBox.style.display = 'flex';
                    document.getElementById('counterAlertText').innerText = m.counter_items[0];
                } else {
                    alertBox.style.display = 'none';
                }
            } else {
                document.getElementById('matchupCard').style.display = 'none';
            }

            // Build rápida
            const b = state.build;
            if (b && b.most_popular) {
                document.getElementById('buildCard').style.display = 'block';
                document.getElementById('skillMaxOrder').innerText = `Max: ${b.most_popular.skills.priority}`;
                
                const pillsContainer = document.getElementById('coreItemsPills');
                pillsContainer.innerHTML = (b.most_popular.items.core || []).map(it => `
                    <span class="item-badge-pill">${it.name}</span>
                `).join('');
            } else {
                document.getElementById('buildCard').style.display = 'none';
            }
        }
        // Modo Selección de Campeones
        else if (state.mode === 'champ_select') {
            viewInGame.style.display = 'none';
            viewChampSelect.style.display = 'block';
            viewIdle.style.display = 'none';

            headerTitle.innerText = state.title;
            pulse.style.background = '#f59e0b';
            pulse.style.boxShadow = '0 0 8px #f59e0b';

            document.getElementById('csChampTitle').innerText = state.champion_name || 'Eligiendo Campeón...';
            document.getElementById('csRoleSubtitle').innerText = `Línea: ${state.role.toUpperCase()}`;
            document.getElementById('draftLockStatus').innerText = state.is_locked ? 'Fijado [OK]' : 'En Hover';
        }
        // Modo Espera (Idle)
        else {
            viewInGame.style.display = 'none';
            viewChampSelect.style.display = 'none';
            viewIdle.style.display = 'block';

            headerTitle.innerText = 'LoL Companion';
            pulse.style.background = state.connected ? '#38bdf8' : '#64748b';
            pulse.style.boxShadow = state.connected ? '0 0 8px #38bdf8' : 'none';

            document.getElementById('idleSummonerName').innerText = state.summoner_name || 'Invocador';
            document.getElementById('idleRank').innerText = state.rank || 'Conectado a LoL';
        }
    });
}
