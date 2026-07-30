from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from backtest.contracts import (
    ActualCoverageSummary,
    ActualPointsRecord,
    FrozenPlayer,
    SlateActualPoints,
    SlateFeatureSnapshot,
)
from backtest.historical.http_cache import CachedHttpResponse, HttpCacheError, ImmutableHttpCache
from backtest.historical.scoring import (
    DK_MLB_CLASSIC_RULES_VERSION,
    HitterGameStats,
    PitcherGameStats,
    score_hitter_game,
    score_pitcher_game,
)
from backtest.io import load_json, write_json


STATSAPI_FEED_URL = "https://statsapi.mlb.com/api/v1.1/game/{game_id}/feed/live"
ACTUALS_BUILDER_VERSION = "mlb-statsapi-full-pool-actuals-v1"
_FINAL_STATES = {"final", "game over", "completed early", "completed early: rain"}


class StatsApiActualsError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedFeed:
    game_id: int
    source_timestamp: datetime
    player_rows: dict[int, dict[str, Any]]
    winner_id: int | None
    artifact_id: str
    raw_path: Path
    response: CachedHttpResponse


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise StatsApiActualsError(f"{field_name} must include a timezone offset")
    return value


def _parse_payload_timestamp(payload: dict[str, Any], fallback: datetime) -> datetime:
    raw = payload.get("metaData", {}).get("timeStamp")
    if isinstance(raw, str):
        for fmt in ("%Y%m%d_%H%M%S", "%Y%m%d_%H%M%S%f"):
            try:
                return datetime.strptime(raw, fmt).replace(tzinfo=UTC)
            except ValueError:
                continue
    return fallback.astimezone(UTC)


def _final_status(payload: dict[str, Any]) -> bool:
    status = payload.get("gameData", {}).get("status", {})
    abstract = str(status.get("abstractGameState", "")).strip().lower()
    detailed = str(status.get("detailedState", "")).strip().lower()
    coded = str(status.get("codedGameState", "")).strip().upper()
    return abstract == "final" or detailed in _FINAL_STATES or coded == "F"


def _int(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise StatsApiActualsError(f"expected integer statistic, got {value!r}") from exc


def _bool_count(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _int(value, 0) > 0


def _outs_from_innings(value: Any) -> int:
    if value in (None, ""):
        return 0
    text = str(value).strip()
    match = re.fullmatch(r"(?P<innings>\d+)(?:\.(?P<outs>[012]))?", text)
    if not match:
        raise StatsApiActualsError(f"invalid inningsPitched value: {value!r}")
    return int(match.group("innings")) * 3 + int(match.group("outs") or 0)


def _role(player: FrozenPlayer) -> Literal["hitter", "pitcher"]:
    normalized = {item.upper() for item in player.position}
    return "pitcher" if normalized == {"P"} else "hitter"


def _appearance_hitter(stats: dict[str, Any]) -> bool:
    if _int(stats.get("plateAppearances"), 0) > 0 or _int(stats.get("atBats"), 0) > 0:
        return True
    return any(
        _int(stats.get(key), 0) > 0
        for key in (
            "hits",
            "doubles",
            "triples",
            "homeRuns",
            "runs",
            "rbi",
            "baseOnBalls",
            "hitByPitch",
            "stolenBases",
            "sacBunts",
            "sacFlies",
        )
    )


def _appearance_pitcher(stats: dict[str, Any]) -> bool:
    return (
        _int(stats.get("outs"), 0) > 0
        or _outs_from_innings(stats.get("inningsPitched")) > 0
        or _int(stats.get("gamesPitched"), 0) > 0
        or _int(stats.get("numberOfPitches"), 0) > 0
    )


def _hitter_record(
    player: FrozenPlayer,
    game_id: int,
    artifact_id: str,
    row: dict[str, Any] | None,
) -> ActualPointsRecord:
    stats = (row or {}).get("stats", {}).get("batting", {})
    if not isinstance(stats, dict) or not _appearance_hitter(stats):
        return ActualPointsRecord(
            mlbam_id=player.mlbam_id,
            actual_points=0.0,
            status="dnp_no_game_appearance" if row else "dnp_not_in_final_boxscore",
            source_game_id=game_id,
            source_evidence_id=artifact_id,
            scoring_components={"role": "hitter", "dnp": True},
        )
    parsed = HitterGameStats(
        mlbam_id=player.mlbam_id,
        game_id=game_id,
        hits=_int(stats.get("hits")),
        doubles=_int(stats.get("doubles")),
        triples=_int(stats.get("triples")),
        home_runs=_int(stats.get("homeRuns")),
        runs=_int(stats.get("runs")),
        rbi=_int(stats.get("rbi")),
        walks=_int(stats.get("baseOnBalls")),
        hit_by_pitch=_int(stats.get("hitByPitch")),
        stolen_bases=_int(stats.get("stolenBases")),
    )
    points = score_hitter_game(parsed)
    components = {
        "role": "hitter",
        "hits": parsed.hits,
        "doubles": parsed.doubles,
        "triples": parsed.triples,
        "home_runs": parsed.home_runs,
        "runs": parsed.runs,
        "rbi": parsed.rbi,
        "walks": parsed.walks,
        "hit_by_pitch": parsed.hit_by_pitch,
        "stolen_bases": parsed.stolen_bases,
        "plate_appearances": _int(stats.get("plateAppearances")),
    }
    return ActualPointsRecord(
        mlbam_id=player.mlbam_id,
        actual_points=points,
        status="played",
        source_game_id=game_id,
        source_evidence_id=artifact_id,
        scoring_components=components,
    )


def _pitcher_record(
    player: FrozenPlayer,
    game_id: int,
    artifact_id: str,
    row: dict[str, Any] | None,
    winner_id: int | None,
) -> ActualPointsRecord:
    stats = (row or {}).get("stats", {}).get("pitching", {})
    if not isinstance(stats, dict) or not _appearance_pitcher(stats):
        return ActualPointsRecord(
            mlbam_id=player.mlbam_id,
            actual_points=0.0,
            status="dnp_no_game_appearance" if row else "dnp_not_in_final_boxscore",
            source_game_id=game_id,
            source_evidence_id=artifact_id,
            scoring_components={"role": "pitcher", "dnp": True},
        )
    outs = _int(stats.get("outs"), -1)
    if outs < 0:
        outs = _outs_from_innings(stats.get("inningsPitched"))
    complete_game = _bool_count(stats.get("completeGames"))
    shutout = _bool_count(stats.get("shutouts"))
    hits_allowed = _int(stats.get("hits"))
    no_hitter = complete_game and hits_allowed == 0
    parsed = PitcherGameStats(
        mlbam_id=player.mlbam_id,
        game_id=game_id,
        outs_recorded=outs,
        strikeouts=_int(stats.get("strikeOuts")),
        win=winner_id == player.mlbam_id,
        earned_runs=_int(stats.get("earnedRuns")),
        hits_allowed=hits_allowed,
        walks_allowed=_int(stats.get("baseOnBalls")),
        hit_batters=_int(stats.get("hitBatsmen", stats.get("hitByPitch", 0))),
        complete_game=complete_game,
        complete_game_shutout=shutout,
        no_hitter=no_hitter,
    )
    points = score_pitcher_game(parsed)
    components = {
        "role": "pitcher",
        "outs_recorded": parsed.outs_recorded,
        "strikeouts": parsed.strikeouts,
        "win": parsed.win,
        "earned_runs": parsed.earned_runs,
        "hits_allowed": parsed.hits_allowed,
        "walks_allowed": parsed.walks_allowed,
        "hit_batters": parsed.hit_batters,
        "complete_game": parsed.complete_game,
        "complete_game_shutout": parsed.complete_game_shutout,
        "no_hitter": parsed.no_hitter,
    }
    return ActualPointsRecord(
        mlbam_id=player.mlbam_id,
        actual_points=points,
        status="played",
        source_game_id=game_id,
        source_evidence_id=artifact_id,
        scoring_components=components,
    )


class StatsApiFullPoolActualsBuilder:
    def __init__(
        self,
        *,
        feature_path: Path,
        output_dir: Path,
        cache: ImmutableHttpCache,
        offline: bool,
        retries: int = 3,
        timeout: float = 20.0,
        scoring_rules_artifact_id: str = "dk-mlb-classic-rules-code-v1",
    ):
        self.feature_path = feature_path.resolve()
        self.output_dir = output_dir.resolve()
        self.cache = cache
        self.offline = offline
        self.retries = retries
        self.timeout = timeout
        self.scoring_rules_artifact_id = scoring_rules_artifact_id

    def build(self) -> dict[str, Any]:
        features = SlateFeatureSnapshot.model_validate(load_json(self.feature_path))
        if features.site != "dk":
            raise StatsApiActualsError("StatsAPI actual reconstruction currently supports DK only")
        if not features.games or not features.game_ids:
            raise StatsApiActualsError("feature snapshot must declare games and game_ids")

        self.output_dir.mkdir(parents=True, exist_ok=True)
        feeds: dict[int, ParsedFeed] = {}
        fetch_audit: list[dict[str, Any]] = []
        for game in features.games:
            parsed = self._load_game(game.game_id)
            feeds[game.game_id] = parsed
            fetch_audit.append(
                {
                    "game_id": game.game_id,
                    "url": parsed.response.url,
                    "raw_file": parsed.raw_path.relative_to(self.output_dir).as_posix(),
                    "byte_count": parsed.response.byte_count,
                    "sha256": parsed.response.sha256,
                    "fetched_at": parsed.response.fetched_at.isoformat(),
                    "from_cache": parsed.response.from_cache,
                    "cache_key": parsed.response.cache_key,
                    "artifact_id": parsed.artifact_id,
                    "source_final": True,
                }
            )

        records: list[ActualPointsRecord] = []
        identity_audit: list[dict[str, Any]] = []
        for player in sorted(features.players, key=lambda item: item.mlbam_id):
            if player.game_id not in feeds:
                raise StatsApiActualsError(
                    f"player {player.mlbam_id} references uncached game {player.game_id}"
                )
            feed = feeds[player.game_id]
            row = feed.player_rows.get(player.mlbam_id)
            role = _role(player)
            if role == "pitcher":
                record = _pitcher_record(
                    player, player.game_id, feed.artifact_id, row, feed.winner_id
                )
            else:
                record = _hitter_record(player, player.game_id, feed.artifact_id, row)
            records.append(record)
            identity_audit.append(
                {
                    "mlbam_id": player.mlbam_id,
                    "external_id": player.external_id,
                    "feature_name": player.name,
                    "game_id": player.game_id,
                    "role": role,
                    "boxscore_identity_present": row is not None,
                    "status": record.status,
                    "mapping_method": "feature_snapshot_mlbam_id_exact",
                    "ambiguity": False,
                }
            )

        feature_ids = {item.mlbam_id for item in features.players}
        actual_ids = {item.mlbam_id for item in records}
        missing = sorted(feature_ids - actual_ids)
        extra = sorted(actual_ids - feature_ids)
        if missing or extra:
            raise StatsApiActualsError(
                f"full-pool identity coverage failed; missing={missing[:20]} extra={extra[:20]}"
            )
        played_count = sum(item.status == "played" for item in records)
        dnp_count = len(records) - played_count
        coverage = ActualCoverageSummary(
            feature_player_count=len(features.players),
            records_count=len(records),
            played_count=played_count,
            dnp_count=dnp_count,
            missing_ids=missing,
            extra_ids=extra,
        )
        source_timestamp = max(item.source_timestamp for item in feeds.values())
        acquired_at = max(
            source_timestamp,
            max(item.response.fetched_at for item in feeds.values()),
        )
        artifact_ids = [feeds[game_id].artifact_id for game_id in features.game_ids]
        actuals = SlateActualPoints(
            schema_version="1.3",
            data_kind=features.data_kind,
            slate_id=features.slate_id,
            site=features.site,
            scoring_source="official_mlb_statsapi_feed_live_reconstruction",
            scoring_rules_version=DK_MLB_CLASSIC_RULES_VERSION,
            acquired_at=acquired_at,
            source_timestamp=source_timestamp,
            source_record_id=";".join(str(game_id) for game_id in features.game_ids),
            source_final=True,
            validation_scope=features.validation_scope,
            coverage_scope="all_feature_players",
            warnings=(
                list(features.warnings)
                + (["provider_game_set_unverified"] if not features.provider_game_set_verified else [])
            ),
            coverage_summary=coverage,
            raw_stats_artifact_ids=artifact_ids,
            scoring_rules_artifact_id=self.scoring_rules_artifact_id,
            points=records,
        )
        actual_path = self.output_dir / f"{features.slate_id}.actuals.json"
        write_json(actual_path, actuals.model_dump(mode="json"))
        identity_path = self.output_dir / "identity-mapping-audit.json"
        write_json(
            identity_path,
            {
                "schema_version": "1.0",
                "slate_id": features.slate_id,
                "mapping_method": "feature_snapshot_mlbam_id_exact",
                "ambiguous_count": 0,
                "unresolved_count": 0,
                "records": identity_audit,
            },
        )
        audit_path = self.output_dir / "actuals-build-audit.json"
        write_json(
            audit_path,
            {
                "schema_version": "1.0",
                "builder_version": ACTUALS_BUILDER_VERSION,
                "slate_id": features.slate_id,
                "feature_file": self.feature_path.name,
                "feature_sha256": hashlib.sha256(self.feature_path.read_bytes()).hexdigest(),
                "offline": self.offline,
                "fetches": fetch_audit,
                "coverage": coverage.model_dump(mode="json"),
                "identity_audit_file": identity_path.name,
                "actuals_file": actual_path.name,
                "actuals_sha256": hashlib.sha256(actual_path.read_bytes()).hexdigest(),
                "status": "PASS_FULL_POOL",
            },
        )
        return {
            "slate_id": features.slate_id,
            "actuals_file": actual_path.name,
            "actuals_sha256": hashlib.sha256(actual_path.read_bytes()).hexdigest(),
            "coverage": coverage.model_dump(mode="json"),
            "audit_file": audit_path.name,
            "identity_audit_file": identity_path.name,
            "raw_game_feeds": fetch_audit,
            "status": "PASS_FULL_POOL",
        }

    def _load_game(self, game_id: int) -> ParsedFeed:
        url = STATSAPI_FEED_URL.format(game_id=game_id)
        try:
            response = self.cache.fetch_json(
                url, offline=self.offline, retries=self.retries, timeout=self.timeout
            )
        except HttpCacheError as exc:
            raise StatsApiActualsError(str(exc)) from exc
        payload = response.json()
        if not isinstance(payload, dict):
            raise StatsApiActualsError(f"StatsAPI payload for game {game_id} is not an object")
        payload_game_id = _int(payload.get("gamePk"), -1)
        if payload_game_id != game_id:
            raise StatsApiActualsError(
                f"StatsAPI gamePk mismatch: expected {game_id}, got {payload_game_id}"
            )
        if not _final_status(payload):
            raise StatsApiActualsError(f"StatsAPI game {game_id} is not final")
        raw_dir = self.output_dir / "raw" / "mlb-statsapi"
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_path = raw_dir / f"game-{game_id}-feed-live.json"
        if raw_path.exists() and raw_path.read_bytes() != response.body:
            raise StatsApiActualsError(f"immutable raw archive collision for game {game_id}")
        raw_path.write_bytes(response.body)
        digest = response.sha256
        artifact_id = f"mlb-statsapi-game-{game_id}-{digest[:12]}"
        teams = payload.get("liveData", {}).get("boxscore", {}).get("teams", {})
        player_rows: dict[int, dict[str, Any]] = {}
        for side in ("away", "home"):
            side_players = teams.get(side, {}).get("players", {})
            if not isinstance(side_players, dict):
                raise StatsApiActualsError(
                    f"StatsAPI game {game_id} has invalid {side} players object"
                )
            for raw_key, row in side_players.items():
                if not isinstance(row, dict):
                    continue
                person = row.get("person", {})
                person_id = person.get("id")
                key_id = raw_key[2:] if isinstance(raw_key, str) and raw_key.startswith("ID") else None
                if person_id is not None and key_id is not None and _int(person_id, -1) != _int(key_id, -1):
                    raise StatsApiActualsError(
                        f"identity ambiguity in game {game_id}: boxscore key {raw_key!r} "
                        f"disagrees with person.id={person_id!r}"
                    )
                raw_id = person_id if person_id is not None else key_id
                player_id = _int(raw_id, -1)
                if player_id < 1:
                    continue
                if player_id in player_rows:
                    raise StatsApiActualsError(
                        f"player {player_id} appears twice in game {game_id} boxscore"
                    )
                player_rows[player_id] = row
        winner = payload.get("liveData", {}).get("decisions", {}).get("winner", {})
        winner_id = _int(winner.get("id"), -1) if isinstance(winner, dict) else -1
        return ParsedFeed(
            game_id=game_id,
            source_timestamp=_parse_payload_timestamp(payload, response.fetched_at),
            player_rows=player_rows,
            winner_id=winner_id if winner_id > 0 else None,
            artifact_id=artifact_id,
            raw_path=raw_path,
            response=response,
        )
