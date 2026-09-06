import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from kloppy.domain import (
    Provider,
    Orientation,
    Point,
    Point3D,
    DatasetType,
)

from kloppy import skillcorner


class TestSkillCornerTracking:
    @pytest.fixture
    def meta_data(self, base_dir) -> str:
        return base_dir / "files/skillcorner_match_data.json"

    @pytest.fixture
    def raw_data(self, base_dir) -> str:
        return base_dir / "files/skillcorner_structured_data.json"

    @pytest.fixture
    def meta_data_v3(self, base_dir) -> str:
        return base_dir / "files/skillcorner_meta_data.json"

    @pytest.fixture
    def raw_data_v3(self, base_dir) -> str:
        return base_dir / "files/skillcorner_v3_raw_data.jsonl"

    @pytest.fixture
    def raw_data_timestamp(self, base_dir) -> str:
        return base_dir / "files/skillcorner_structured_data_timestamp.json"

    def test_correct_deserialization_timestamp(
        self, raw_data_timestamp: Path, meta_data: Path
    ):
        skillcorner.load(
            meta_data=meta_data,
            raw_data=raw_data_timestamp,
            coordinates="skillcorner",
            include_empty_frames=True,
        )

    def test_correct_deserialization(self, raw_data: Path, meta_data: Path):
        dataset = skillcorner.load(
            meta_data=meta_data,
            raw_data=raw_data,
            coordinates="skillcorner",
            include_empty_frames=True,
        )

        assert dataset.metadata.provider == Provider.SKILLCORNER
        assert dataset.dataset_type == DatasetType.TRACKING
        assert len(dataset.records) == 55632
        assert len(dataset.metadata.periods) == 2
        assert dataset.metadata.orientation == Orientation.AWAY_HOME
        assert dataset.metadata.periods[0].id == 1
        assert dataset.metadata.periods[0].start_timestamp == timedelta(
            seconds=1411 / 10
        )
        assert dataset.metadata.periods[0].end_timestamp == timedelta(
            seconds=28944 / 10
        )
        assert dataset.metadata.periods[1].id == 2
        assert dataset.metadata.periods[1].start_timestamp == timedelta(
            seconds=39979 / 10
        )
        assert dataset.metadata.periods[1].end_timestamp == timedelta(
            seconds=68076 / 10
        )

        assert dataset.records[0].frame_id == 1411
        assert dataset.records[0].timestamp == timedelta(seconds=0)
        assert dataset.records[27534].frame_id == 39979
        assert dataset.records[27534].timestamp == timedelta(seconds=0)

        # make sure skillcorner ID is used as player ID
        assert dataset.metadata.teams[0].players[0].player_id == "10247"

        # make sure data is loaded correctly
        home_player = dataset.metadata.teams[0].players[2]
        assert dataset.records[112].players_data[
            home_player
        ].coordinates == Point(x=33.8697315398, y=-9.55742259253)

        away_player = dataset.metadata.teams[1].players[9]
        assert dataset.records[112].players_data[
            away_player
        ].coordinates == Point(x=25.9863082795, y=27.3013598578)

        assert dataset.records[113].ball_coordinates == Point3D(
            x=30.5914728131, y=35.3622277834, z=2.24371228757
        )

        # check that missing ball-z_coordinate is identified as None
        assert dataset.records[150].ball_coordinates == Point3D(
            x=11.6568802848, y=24.7214038909, z=None
        )

        # check that 'ball_z' column is included in to_pandas dataframe
        # frame = _frame_to_pandas_row_converter(dataset.records[150])
        # assert "ball_z" in frame.keys()

        # make sure player data is only in the frame when the player is in view
        assert "home_1" not in [
            player.player_id
            for player in dataset.records[112].players_data.keys()
        ]

        assert "away_1" not in [
            player.player_id
            for player in dataset.records[112].players_data.keys()
        ]

        # are anonymous players loaded correctly?
        home_anon_75 = [
            player
            for player in dataset.records[197].players_data
            if player.player_id == "home_anon_75"
        ]
        assert home_anon_75 == [
            player
            for player in dataset.records[200].players_data
            if player.player_id == "home_anon_75"
        ]

        # is pitch dimension set correctly?
        pitch_dimensions = dataset.metadata.pitch_dimensions
        assert pitch_dimensions.x_dim.min == -52.5
        assert pitch_dimensions.x_dim.max == 52.5
        assert pitch_dimensions.y_dim.min == -34
        assert pitch_dimensions.y_dim.max == 34

        # Check enriched metadata
        date = dataset.metadata.date
        if date:
            assert isinstance(date, datetime)
            assert date == datetime(
                2019, 11, 9, 17, 30, 0, tzinfo=timezone.utc
            )

        game_id = dataset.metadata.game_id
        if game_id:
            assert isinstance(game_id, str)
            assert game_id == "2417"

        home_coach = dataset.metadata.home_coach
        if home_coach:
            assert isinstance(home_coach, str)
            assert home_coach == "Hans-Dieter Flick"

        away_coach = dataset.metadata.away_coach
        if away_coach:
            assert isinstance(away_coach, str)
            assert away_coach == "Lucien Favre"

    def test_correct_normalized_deserialization(
        self, meta_data: str, raw_data: str
    ):
        dataset = skillcorner.load(meta_data=meta_data, raw_data=raw_data)

        home_player = dataset.metadata.teams[0].players[2]
        assert dataset.records[0].players_data[
            home_player
        ].coordinates == Point(x=0.8225688718076191, y=0.6405503322430883)

    def test_skip_empty_frames(self, meta_data: str, raw_data: str):
        dataset = skillcorner.load(
            meta_data=meta_data, raw_data=raw_data, include_empty_frames=False
        )

        assert len(dataset.records) == 34783
        assert dataset.records[0].timestamp == timedelta(seconds=11.2)

    def test_correct_deserialization_v3(
        self, raw_data_v3: Path, meta_data_v3: Path
    ):
        dataset = skillcorner.load(
            meta_data=meta_data_v3,
            raw_data=raw_data_v3,
            coordinates="skillcorner",
            include_empty_frames=True,
        )

        assert dataset.metadata.provider == Provider.SKILLCORNER
        assert dataset.dataset_type == DatasetType.TRACKING
        assert len(dataset.records) == 27
        assert len(dataset.metadata.periods) == 2
        assert dataset.metadata.periods[0].id == 1
        assert dataset.metadata.periods[0].start_timestamp == timedelta(
            seconds=1
        )
        assert dataset.metadata.periods[0].end_timestamp == timedelta(
            seconds=2, microseconds=200000
        )
        assert dataset.metadata.periods[1].id == 2
        assert dataset.metadata.periods[1].start_timestamp == timedelta(
            seconds=6097, microseconds=700000
        )
        assert dataset.metadata.periods[1].end_timestamp == timedelta(
            seconds=6099
        )

        assert dataset.records[0].frame_id == 10
        assert dataset.records[0].timestamp == timedelta(seconds=0)
        assert dataset.records[-1].frame_id == 60990
        assert dataset.records[-1].timestamp == timedelta(seconds=3256)

        home_team_gk = dataset.metadata.teams[0].get_player_by_id("133")
        assert home_team_gk.player_id == "133"
        assert dataset.records[10].players_data[
            home_team_gk
        ].coordinates == Point(x=40.46, y=-0.58)

        away_team_gk = dataset.metadata.teams[1].get_player_by_id("76")
        assert away_team_gk.player_id == "76"
        assert dataset.records[10].players_data[
            away_team_gk
        ].coordinates == Point(x=-41.97, y=-0.61)

    def test_v3_unknown_player_id_is_skipped(
        self, raw_data_v3: Path, meta_data_v3: Path, tmp_path: Path, caplog
    ):
        """A player id in the frames but not in the metadata must not fail the match.

        SkillCorner ship this: the tracking file references a player id their
        own match endpoint 404s on (observed on FC Eindhoven - MVV Maastricht,
        2026-08-14, id 1075530). Before the guard, deserialize raised KeyError
        and the whole match was lost.
        """
        unknown_id = 99999999
        patched = tmp_path / "raw_with_unknown_player.jsonl"
        with open(raw_data_v3) as src, open(patched, "w") as dst:
            for line in src:
                if not line.strip():
                    continue
                frame = json.loads(line)
                if frame.get("player_data"):
                    frame["player_data"].append(
                        {
                            "x": 1.0,
                            "y": 2.0,
                            "player_id": unknown_id,
                            "is_detected": True,
                        }
                    )
                dst.write(json.dumps(frame) + "\n")

        with caplog.at_level(logging.WARNING):
            dataset = skillcorner.load(
                meta_data=meta_data_v3,
                raw_data=patched,
                coordinates="skillcorner",
                include_empty_frames=True,
            )

        # Every frame still lands, and the known players are untouched.
        assert len(dataset.records) == 27
        home_team_gk = dataset.metadata.teams[0].get_player_by_id("133")
        assert dataset.records[10].players_data[
            home_team_gk
        ].coordinates == Point(x=40.46, y=-0.58)

        # The unknown id reaches no player object.
        for record in dataset.records:
            for player in record.players_data:
                assert player.player_id != str(unknown_id)

        # Warned about exactly once, not once per frame.
        warnings = [
            r for r in caplog.records if str(unknown_id) in r.getMessage()
        ]
        assert len(warnings) == 1
