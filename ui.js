// KPFM 공용 스크립트: 테마, 보기(Wide/Compact), 티어 계산, 아이콘, 경기 상세.
// index.html과 user.html이 <head>에서 이 파일을 먼저 불러온다 (첫 화면의 테마가 깜빡이지 않도록).
(function () {
    const root = document.documentElement;
    const store = {
        get(key) { try { return localStorage.getItem(key); } catch (e) { return null; } },
        set(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* 저장 불가여도 화면은 정상 동작 */ } },
    };

    // ---- 아이콘 (lucide, 24x24 기준 stroke 1.5)
    const ICONS = {
        sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>',
        moon: '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
        back: '<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>',
        left: '<path d="m15 18-6-6 6-6"/>',
        right: '<path d="m9 18 6-6-6-6"/>',
        down: '<path d="m6 9 6 6 6-6"/>',
        x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
        arrowDown: '<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>',
        arrowUp: '<path d="m5 12 7-7 7 7"/><path d="M12 19V5"/>',
        search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    };
    function icon(name, size) {
        const s = size || 16;
        return `<svg class="icon" width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name]}</svg>`;
    }

    // ---- 테마
    let theme = store.get('theme') === 'light' ? 'light' : 'dark';
    root.setAttribute('data-theme', theme);

    // ---- 보기: wide(넓은 앱) / compact(예전의 좁은 카드형). 1024px 미만은 항상 compact
    const layoutPref = () => (store.get('layout') === 'compact' ? 'compact' : 'wide');
    const effectiveLayout = () => (layoutPref() === 'compact' || window.innerWidth < 1024 ? 'compact' : 'wide');
    root.setAttribute('data-layout', effectiveLayout());

    function applyLayout() {
        const next = effectiveLayout();
        if (root.getAttribute('data-layout') !== next) {
            root.setAttribute('data-layout', next);
            window.dispatchEvent(new CustomEvent('layoutchange'));
        }
        document.querySelectorAll('[data-layout-pref]').forEach(btn => {
            btn.setAttribute('aria-pressed', String(btn.getAttribute('data-layout-pref') === layoutPref()));
        });
    }

    function init() {
        const themeBtn = document.getElementById('themeToggleBtn');
        if (themeBtn) {
            const paint = () => {
                // 아이콘은 "눌렀을 때 바뀌는 테마"를 보여 준다 (기존 동작과 같음)
                themeBtn.innerHTML = icon(theme === 'light' ? 'moon' : 'sun');
                const label = theme === 'light' ? 'Switch to dark theme' : 'Switch to light theme';
                themeBtn.setAttribute('aria-label', label);
                themeBtn.title = label;
            };
            paint();
            themeBtn.addEventListener('click', () => {
                theme = theme === 'light' ? 'dark' : 'light';
                root.setAttribute('data-theme', theme);
                store.set('theme', theme);
                paint();
                window.dispatchEvent(new CustomEvent('themechange'));
            });
        }
        document.querySelectorAll('[data-layout-pref]').forEach(btn => {
            btn.addEventListener('click', () => {
                store.set('layout', btn.getAttribute('data-layout-pref'));
                applyLayout();
            });
        });
        applyLayout();
    }
    document.addEventListener('DOMContentLoaded', init);
    window.addEventListener('resize', applyLayout);

    // ---- 티어: 100점 단위, Gold 3 = 1500~1599 (engine.py의 calculate_tier와 같은 규칙)
    const TIERS = [
        'Copper 3', 'Copper 2', 'Copper 1', 'Bronze 3', 'Bronze 2', 'Bronze 1',
        'Silver 3', 'Silver 2', 'Silver 1', 'Gold 3', 'Gold 2', 'Gold 1',
        'Platinum 3', 'Platinum 2', 'Platinum 1', 'Diamond 3', 'Diamond 2', 'Diamond 1', 'Champion',
    ];
    const PLACEMENT_GAMES = 5; // 이 경기 수 이하는 배치중, 6경기부터 정식 티어

    function tierInfo(elo) {
        const raw = Math.floor((elo - 1500) / 100) + 9;
        const index = Math.max(0, Math.min(raw, TIERS.length - 1));
        const low = 1500 + (index - 9) * 100;
        const pos = raw < 0 ? 0 : Math.max(0, Math.min(1, (elo - low) / 100));
        const name = TIERS[index];
        return { index, name, short: name.replace('Platinum', 'Plat'), group: name.split(' ')[0].toLowerCase(), low, high: low + 100, pos };
    }
    function tierShort(name) {
        return String(name || '').replace('Platinum', 'Plat');
    }

    // 티어 글자: 점 + 이름 (배치 중이면 빈 점 + 경기 수)
    function tierHTML(tierName, matches) {
        if (matches <= PLACEMENT_GAMES) {
            return `<span class="tier placement" title="6경기부터 정식 티어"><i class="dot"></i>Placement ${matches}/${PLACEMENT_GAMES}</span>`;
        }
        const group = String(tierName || 'Unranked').split(' ')[0].toLowerCase();
        return `<span class="tier tier-${group}"><i class="dot"></i>${tierShort(tierName || 'Unranked')}</span>`;
    }

    // 티어 눈금자: 현재 티어 구간 안에서의 위치
    function rulerHTML(elo, large) {
        const t = tierInfo(elo);
        return `<span class="ruler${large ? ' ruler-lg' : ''}" style="--pos:${(t.pos * 100).toFixed(1)}%" title="${t.name} · ${Math.round(t.pos * 100)} / 100"><i></i></span>`;
    }

    // ---- 기타 도구
    function esc(text) {
        return String(text ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    }
    function cssVar(name) {
        return getComputedStyle(root).getPropertyValue(name).trim();
    }
    function goToPlayer(nickname) {
        window.location.href = `user.html?nickname=${encodeURIComponent(nickname)}&t=${Date.now()}`;
    }

    // ---- 경기 상세 (두 페이지가 같은 표를 쓴다)
    function eloChange(allAftercalc, nickname, round) {
        const nick = nickname.trim().toLowerCase();
        const rNum = parseInt(round);
        const current = allAftercalc.find(e => parseInt(e.Round) === rNum && e.Nickname?.trim().toLowerCase() === nick);
        if (!current) return { elo: 1500, diff: 0 };
        const elo = parseInt(current.ELO || 1500);
        const before = allAftercalc
            .filter(e => parseInt(e.Round) < rNum && e.Nickname?.trim().toLowerCase() === nick)
            .sort((a, b) => parseInt(b.Round) - parseInt(a.Round))[0];
        return { elo, diff: elo - (before ? parseInt(before.ELO || 1500) : 1500) };
    }

    function renderMatchDetails(round, allMatches, allAftercalc, tbody) {
        tbody.innerHTML = '';
        const players = allMatches.filter(p => String(p.Round) === String(round));
        const sides = [1, 2].map(team => {
            const list = players.filter(p => p.Team === String(team)).map(p => ({ p, ...eloChange(allAftercalc, p.Nickname, round) }));
            const best = list.reduce((m, x) => (x.diff > (m ? m.diff : -Infinity) ? x : m), null);
            return { list, mvp: best ? best.p.Nickname : '' };
        });
        const rows = Math.max(sides[0].list.length, sides[1].list.length);

        const cells = (side, i) => {
            const x = side.list[i];
            if (!x) return '<td></td><td></td><td></td><td></td>';
            const sign = x.diff >= 0 ? '+' : '';
            return `<td class="name${x.p.Nickname === side.mvp ? ' mvp' : ''}" data-nickname="${esc(x.p.Nickname)}"${x.p.Nickname === side.mvp ? ' title="MVP: ELO gain"' : ''}>${esc(x.p.Nickname)}</td>
                    <td class="num">${esc(x.p.Kills || '0')}</td>
                    <td class="num">${esc(x.p.Deaths || '0')}</td>
                    <td class="num">${x.elo} <span class="${x.diff >= 0 ? 'positive' : 'negative'}">${sign}${x.diff}</span></td>`;
        };

        for (let i = 0; i < rows; i++) {
            const tr = document.createElement('tr');
            tr.innerHTML = cells(sides[0], i) + cells(sides[1], i);
            tr.querySelectorAll('.name').forEach(td => {
                const nick = td.getAttribute('data-nickname');
                if (nick) td.addEventListener('click', () => goToPlayer(nick));
            });
            tbody.appendChild(tr);
        }
    }

    // ---- 보정값: 상대·팀원 강도를 뺀 킬/데스 성적 (insight.csv). 점선 밑줄을 누르면 설명이 뜬다
    function adjHTML(value) {
        return `<button type="button" class="adj" data-adj="${esc(value)}" aria-haspopup="true">보정값 ${esc(value)}</button>`;
    }

    function adjExplain(value) {
        const v = parseFloat(value);
        const pct = Math.round(Math.abs(v - 1) * 100);
        const meaning = pct === 0 ? '평균과 같다는 뜻입니다.'
            : `비슷한 상대 기준 평균보다 킬/데스 비율이 약 ${pct}% ${v > 1 ? '높다' : '낮다'}는 뜻입니다.`;
        return `<strong>보정값 ${esc(value)}</strong>
            <p>상대와 팀원의 강도를 빼고 본 킬/데스 성적입니다. 1.00이 평균이고, ${meaning}</p>
            <p>상대의 실력도 그 상대가 만난 상대로 다시 검증하는 방식으로 모든 선수를 한꺼번에 계산합니다. 승패와 ELO는 쓰지 않습니다.</p>
            <p>경기 수가 적으면 1.00 쪽으로 당겨져 보이므로 5경기 이하는 참고만 하세요.</p>`;
    }

    let popover = null;
    let popoverOwner = null;
    function closePopover() {
        if (popover) popover.remove();
        popover = null;
        popoverOwner = null;
    }
    document.addEventListener('click', (e) => {
        const target = e.target.closest ? e.target.closest('.adj') : null;
        if (!target) {
            if (popover && !popover.contains(e.target)) closePopover();
            return;
        }
        e.stopPropagation(); // 행 클릭(선수 페이지 이동)으로 번지지 않게
        const same = popoverOwner === target;
        closePopover();
        if (same) return;
        popover = document.createElement('div');
        popover.className = 'pop';
        popover.setAttribute('role', 'tooltip');
        popover.innerHTML = adjExplain(target.getAttribute('data-adj'));
        document.body.appendChild(popover);
        popoverOwner = target;
        const r = target.getBoundingClientRect();
        const w = popover.offsetWidth;
        const left = Math.max(8, Math.min(window.innerWidth - w - 8, r.left));
        const below = r.bottom + 8 + popover.offsetHeight < window.innerHeight || r.top < popover.offsetHeight + 16;
        popover.style.left = `${left}px`;
        popover.style.top = `${below ? r.bottom + 8 : r.top - popover.offsetHeight - 8}px`;
    }, true);
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closePopover(); });
    window.addEventListener('scroll', closePopover, true);
    window.addEventListener('resize', closePopover);

    // insight.csv -> { 소문자 닉네임: {adj, text, games} } (파일이 없거나 깨져도 화면은 정상 동작)
    function parseInsights(text) {
        const map = {};
        try {
            const rows = text.replace(/^\uFEFF/, '').trim().split(/\r?\n/);
            const headers = rows[0].split(',').map(h => h.trim());
            rows.slice(1).forEach(line => {
                const v = line.split(',').map(x => x.trim());
                const o = Object.fromEntries(headers.map((h, i) => [h, v[i]]));
                if (o.Nickname) map[o.Nickname.toLowerCase()] = { adj: o.Adj, text: o.Text || '', games: parseInt(o.Games, 10) || 0 };
            });
        } catch (e) { /* 무시 */ }
        return map;
    }

    window.UI = { adjHTML, parseInsights, closePopover, icon, tierInfo, tierShort, tierHTML, rulerHTML, esc, cssVar, goToPlayer, renderMatchDetails, TIERS, PLACEMENT_GAMES };
})();
