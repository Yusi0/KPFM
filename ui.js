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
    // 시즌 구간 (insight.py의 SEASONS와 같아야 한다). 1시즌은 KPT(토너먼트) 스크림, 2시즌부터 KPS 유저가 포함된다
    const SEASONS = [
        { id: '1', name: 'Season 1', sub: 'KPT scrim', first: 1, last: 92 },
        { id: '2', name: 'Season 2', sub: 'KPS', first: 93, last: Infinity },
    ];
    const KPT_LAST_ROUND = SEASONS[0].last;
    const isKPT = (round) => Number(round) <= KPT_LAST_ROUND;
    const inSeason = (round, id) => {
        if (id === 'all') return true;
        const s = SEASONS.find(x => x.id === id);
        return !!s && Number(round) >= s.first && Number(round) <= s.last;
    };
    const seasonLabel = (id) => (SEASONS.find(x => x.id === id) || {}).name || 'All';
    const seasonOf = (round) => (SEASONS.find(s => inSeason(round, s.id)) || {}).id;
    const LATEST_SEASON = SEASONS[SEASONS.length - 1].id;
    // 고른 시즌은 두 화면이 함께 쓴다 ('all' | '1' | '2'). 처음에는 진행 중인 시즌
    function getSeason() {
        try {
            const v = localStorage.getItem('season');
            if (v === 'all' || SEASONS.some(s => s.id === v)) return v;
        } catch (e) { /* 저장소가 막혀도 동작 */ }
        return LATEST_SEASON;
    }
    function setSeason(id) {
        try { localStorage.setItem('season', id); } catch (e) { /* 무시 */ }
    }
    // All / Season 1 / Season 2 탭을 el 안에 그린다. 고르면 onChange(id)
    // options.current: 처음 눌린 탭 (없으면 저장된 값), options.available: 고를 수 있는 탭 (없으면 전부)
    function mountSeasonTabs(el, onChange, options) {
        const { current = getSeason(), available } = options || {};
        const items = [{ id: 'all', name: 'All', sub: 'Career record · no ELO' }, ...SEASONS];
        el.innerHTML = items.map(s => {
            const off = !!available && !available.includes(s.id);
            const range = off ? 'No matches' : s.id === 'all' ? s.sub : `Rounds ${s.first}${s.last === Infinity ? '+' : '–' + s.last} · ${s.sub}`;
            return `<button type="button" data-season="${s.id}" aria-pressed="${s.id === current}" title="${range}"${off ? ' disabled' : ''}>${s.name}</button>`;
        }).join('');
        el.querySelectorAll('button').forEach(btn => btn.addEventListener('click', () => {
            el.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', String(b === btn)));
            setSeason(btn.dataset.season);
            onChange(btn.dataset.season);
        }));
    }

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
            .filter(e => parseInt(e.Round) < rNum && seasonOf(e.Round) === seasonOf(rNum) && e.Nickname?.trim().toLowerCase() === nick)
            .sort((a, b) => parseInt(b.Round) - parseInt(a.Round))[0];
        return { elo, diff: elo - (before ? parseInt(before.ELO || 1500) : 1500) };
    }

    // showElo가 false면(전체 보기) ELO 열과 MVP 표시를 감춘다
    function renderMatchDetails(round, allMatches, allAftercalc, tbody, showElo) {
        tbody.innerHTML = '';
        tbody.closest('table')?.classList.toggle('no-elo', !showElo);
        const players = allMatches.filter(p => String(p.Round) === String(round));
        const sides = [1, 2].map(team => {
            const list = players.filter(p => p.Team === String(team)).map(p => ({ p, ...eloChange(allAftercalc, p.Nickname, round) }));
            const best = list.reduce((m, x) => (x.diff > (m ? m.diff : -Infinity) ? x : m), null);
            return { list, mvp: best && showElo ? best.p.Nickname : '' };
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

        const wire = (tr) => {
            tr.querySelectorAll('.name').forEach(td => {
                const nick = td.getAttribute('data-nickname');
                if (nick) td.addEventListener('click', () => goToPlayer(nick));
            });
        };

        // 좁은 화면: 두 팀을 위아래로 쌓아 가로 스크롤이 생기지 않게 한다 (4열)
        const table = tbody.closest('table');
        const narrow = window.innerWidth < 600;
        if (table) table.classList.toggle('stacked', narrow);
        if (narrow) {
            [['Phantom', 1], ['Ghost', 2]].forEach(([label, team], si) => {
                const head = document.createElement('tr');
                head.className = 'team-row';
                head.innerHTML = `<td><span class="team"><i class="team-mark team-${team}"></i>${label}</span></td><td class="r">K</td><td class="r">D</td><td>ELO</td>`;
                tbody.appendChild(head);
                sides[si].list.forEach((_x, i) => {
                    const tr = document.createElement('tr');
                    tr.innerHTML = cells(sides[si], i);
                    wire(tr);
                    tbody.appendChild(tr);
                });
            });
            return;
        }

        for (let i = 0; i < rows; i++) {
            const tr = document.createElement('tr');
            tr.innerHTML = cells(sides[0], i) + cells(sides[1], i);
            wire(tr);
            tbody.appendChild(tr);
        }
    }

    // ---- 보정값: 상대·팀원 강도를 뺀 킬/데스 성적 (insight.csv). 점선 밑줄을 누르면 설명이 뜬다
    function adjHTML(value) {
        return `<button type="button" class="adj" data-adj="${esc(value)}" aria-haspopup="true">보정값 ${adjIndex(value)}</button>`;
    }

    // 화면에는 100이 평균인 정수로 보인다 (KDR의 소수 두 자리와 헷갈리지 않게). 파일에는 1.00이 평균인 배율로 저장돼 있다
    function adjIndex(value) {
        const v = parseFloat(value);
        return Number.isFinite(v) ? Math.round(v * 100) : null;
    }

    function adjExplain(value) {
        const idx = adjIndex(value);
        const pct = idx === null ? 0 : Math.abs(idx - 100);
        const meaning = idx === null ? '예를 들어 120이면 비슷한 상대 기준 평균보다 킬/데스 비율이 약 20% 높다는 뜻입니다.'
            : pct === 0 ? '이 선수는 평균과 같습니다.'
            : `이 선수는 비슷한 상대 기준 평균보다 킬/데스 비율이 약 ${pct}% ${idx > 100 ? '높습니다' : '낮습니다'}.`;
        return `<strong>보정값${idx === null ? '' : ' ' + idx}</strong>
            <p>상대와 팀원의 수준을 빼고 본 킬/데스 성적입니다. 100이 평균입니다. ${meaning}</p>
            <p>상대의 실력도 그 상대가 만난 상대로 다시 검증해서 모든 선수를 한꺼번에 계산합니다. 승패와 ELO는 쓰지 않습니다.</p>
            <p>5경기 이하는 평균 쪽으로 당겨지므로 참고만 하세요.</p>`;
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

    // rounds.csv → { 라운드: 'YYYY-MM-DD' }. 날짜는 없어도 되는 정보라 파일이 없거나 깨져도 빈 객체
    function parseRoundDates(text) {
        const map = {};
        try {
            text.replace(/^\uFEFF/, '').trim().split(/\r?\n/).slice(1).forEach(line => {
                const [r, d] = line.split(',').map(x => x.trim());
                if (r && /^\d{4}-\d{2}-\d{2}$/.test(d || '')) map[r] = d;
            });
        } catch (e) { /* 무시 */ }
        return map;
    }
    const dateShort = (d) => (d ? d.slice(5).replace('-', '/') : ''); // 2026-10-05 → 10/05

    // 쉼표로만 나누는 단순 CSV (우리 파일은 값에 쉼표가 없다)
    function parseRows(text) {
        const lines = String(text || '').replace(/^\uFEFF/, '').trim().split(/\r?\n/);
        const headers = lines[0].split(',').map(h => h.trim());
        return lines.slice(1).map(line => {
            const v = line.split(',').map(x => x.trim());
            return Object.fromEntries(headers.map((h, i) => [h, v[i]]));
        });
    }

    // seasonboard.csv → { 시즌: { 닉네임(소문자): { elo, tier, total } } }
    function parseSeasonBoard(text) {
        const map = {};
        parseRows(text).forEach(o => {
            if (o.Nickname && o.Season) {
                (map[o.Season] = map[o.Season] || {})[o.Nickname.toLowerCase()] = { elo: parseInt(o.ELO, 10) || 0, tier: o.Tier || 'Unranked', total: parseInt(o.Total, 10) || 0 };
            }
        });
        return map;
    }

    // seasoninsight.csv → { 시즌: { 닉네임(소문자): { adj, text } } } (파일이 없거나 깨져도 화면은 정상 동작)
    function parseSeasonInsights(text) {
        const map = {};
        try {
            parseRows(text).forEach(o => {
                if (o.Nickname && o.Season) (map[o.Season] = map[o.Season] || {})[o.Nickname.toLowerCase()] = { adj: parseFloat(o.Adj), text: o.Text || '' };
            });
        } catch (e) { /* 무시 */ }
        return map;
    }

    window.UI = { SEASONS, inSeason, seasonLabel, getSeason, setSeason, mountSeasonTabs, seasonOf, LATEST_SEASON, parseRows, parseSeasonBoard, parseSeasonInsights, parseRoundDates, dateShort, adjHTML, adjIndex, closePopover, icon, tierInfo, tierShort, tierHTML, rulerHTML, esc, cssVar, goToPlayer, renderMatchDetails, TIERS, PLACEMENT_GAMES, KPT_LAST_ROUND, isKPT };
})();
