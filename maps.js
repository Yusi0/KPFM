// 맵 표시 이름. index.html과 user.html이 함께 사용합니다.
// 새 맵이 생기면 여기에만 추가하세요. 키는 data/source/matches.csv의 Map 값(소문자)입니다.
// 여기에 없는 맵은 CSV에 적힌 이름이 그대로 표시됩니다.
const MAP_NAMES = {
    metro: "Metro",
    warehouse: "Warehouse",
    desert: "Desert Storm",
    elevation: "Elevation",
    derrick: "Derrick",
    containers: "Containers O' Fun",
    suburbia: "Suburbia",
    bazaar: "Bazaar",
    mall: "Mall",
};

function mapDisplayName(raw) {
    const key = String(raw ?? '').toLowerCase();
    return MAP_NAMES[key] || raw;
}
