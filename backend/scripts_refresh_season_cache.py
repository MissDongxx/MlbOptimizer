from datetime import UTC, datetime

from services.season_cache import refresh_season_splits


if __name__ == "__main__":
    data = refresh_season_splits(datetime.now(UTC).year)
    print(
        {
            "season": data.get("season"),
            "last_updated": data.get("last_updated"),
            "players": len(data.get("players", {})),
        }
    )
