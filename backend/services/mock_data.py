from __future__ import annotations

from datetime import UTC, datetime

from models.schemas import GameSummary, Player, Starter


def mock_games() -> list[GameSummary]:
    return [
        GameSummary(
            game_id=1001,
            game_time=datetime.now(UTC).replace(hour=23, minute=5, second=0).isoformat(),
            away_team="LAD",
            home_team="NYY",
            away_starter=Starter(name="Gerrit Cole", mlbam_id=543037, hand="R"),
            home_starter=Starter(name="Tyler Glasnow", mlbam_id=607192, hand="R"),
            away_lineup_confirmed=True,
            home_lineup_confirmed=True,
            venue="Yankee Stadium",
        ),
        GameSummary(
            game_id=1002,
            game_time=datetime.now(UTC).replace(hour=23, minute=40, second=0).isoformat(),
            away_team="ATL",
            home_team="HOU",
            away_starter=Starter(name="Framber Valdez", mlbam_id=664285, hand="L"),
            home_starter=Starter(name="Spencer Strider", mlbam_id=675911, hand="R"),
            away_lineup_confirmed=False,
            home_lineup_confirmed=False,
            venue="Minute Maid Park",
        ),
    ]


def mock_players() -> list[Player]:
    now = datetime.now(UTC)
    raw = [
        (660271, "Shohei Ohtani", "LAD", "NYY", ["OF"], 5600, 4300, 1, "Gerrit Cole", "R", 12.4),
        (605141, "Mookie Betts", "LAD", "NYY", ["2B", "OF"], 5200, 4100, 2, "Gerrit Cole", "R", 10.9),
        (518692, "Freddie Freeman", "LAD", "NYY", ["1B"], 4700, 3700, 3, "Gerrit Cole", "R", 9.7),
        (669257, "Will Smith", "LAD", "NYY", ["C"], 3400, 3300, 4, "Gerrit Cole", "R", 8.6),
        (666158, "Gavin Lux", "LAD", "NYY", ["2B", "SS"], 2800, 2400, 7, "Gerrit Cole", "R", 6.4),
        (592450, "Aaron Judge", "NYY", "LAD", ["OF"], 5600, 4300, 2, "Tyler Glasnow", "R", 11.8),
        (665742, "Juan Soto", "NYY", "LAD", ["OF"], 5400, 4200, 1, "Tyler Glasnow", "R", 11.2),
        (650402, "Giancarlo Stanton", "NYY", "LAD", ["OF"], 3200, 3000, 5, "Tyler Glasnow", "R", 7.9),
        (683011, "Anthony Volpe", "NYY", "LAD", ["SS"], 2900, 2900, 8, "Tyler Glasnow", "R", 6.8),
        (518934, "DJ LeMahieu", "NYY", "LAD", ["1B", "3B"], 2300, 2300, 9, "Tyler Glasnow", "R", 5.9),
        (543037, "Gerrit Cole", "NYY", "LAD", ["P"], 8300, 10000, None, "LAD", "R", 20.1),
        (607192, "Tyler Glasnow", "LAD", "NYY", ["P"], 7900, 9600, None, "NYY", "R", 19.2),
        (621566, "Matt Olson", "ATL", "HOU", ["1B"], 4800, 3800, None, "Framber Valdez", "L", 9.4),
        (621020, "Austin Riley", "ATL", "HOU", ["3B"], 3900, 3600, None, "Framber Valdez", "L", 8.8),
        (645277, "Ozzie Albies", "ATL", "HOU", ["2B"], 4300, 3500, None, "Framber Valdez", "L", 8.9),
        (663586, "Ronald Acuna Jr.", "ATL", "HOU", ["OF"], 5500, 4300, None, "Framber Valdez", "L", 10.7),
        (514888, "Jose Altuve", "HOU", "ATL", ["2B"], 3600, 3500, None, "Spencer Strider", "R", 8.5),
        (670541, "Yordan Alvarez", "HOU", "ATL", ["OF"], 4400, 4000, None, "Spencer Strider", "R", 9.9),
        (665161, "Kyle Tucker", "HOU", "ATL", ["OF"], 4300, 3900, None, "Spencer Strider", "R", 9.6),
        (664285, "Framber Valdez", "HOU", "ATL", ["P"], 7600, 9000, None, "ATL", "R", 17.8),
        (675911, "Spencer Strider", "ATL", "HOU", ["P"], 8800, 10400, None, "HOU", "R", 22.4),
    ]
    players: list[Player] = []
    for row in raw:
        (
            mlbam_id,
            name,
            team,
            opp,
            position,
            salary_dk,
            salary_fd,
            order,
            opp_pitcher,
            hand,
            projection,
        ) = row
        players.append(
            Player(
                mlbam_id=mlbam_id,
                name=name,
                team=team,
                opponent=opp,
                position=position,
                salary_dk=salary_dk,
                salary_fd=salary_fd,
                batting_order=order,
                opposing_pitcher=opp_pitcher,
                opposing_pitcher_hand=hand,
                lineup_status="confirmed" if order else "unconfirmed",
                projected_dk=round(projection, 2),
                projected_fd=round(projection * 1.08, 2),
                projection_source="mock_projection",
                last_15_avg_dk=round(projection / 1.03, 2),
                vs_lhp_avg=round(projection * 0.96, 2),
                vs_rhp_avg=round(projection * 1.04, 2),
                last_updated=now,
            )
        )
    return players
