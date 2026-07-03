from datetime import UTC, datetime

from services.season_cache import refresh_season_splits
from services.vegas import refresh_vegas_lines


if __name__ == "__main__":
    data = refresh_season_splits(datetime.now(UTC).year)
    vegas = refresh_vegas_lines()
    print(
        {
            "season": data.get("season"),
            "last_updated": data.get("last_updated"),
            "players": len(data.get("players", {})),
            "vegas_source": vegas.get("source"),
            "vegas_teams": len(vegas.get("teams", {})),
        }
    )
