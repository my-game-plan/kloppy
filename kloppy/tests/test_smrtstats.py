import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast

import pytest

from kloppy import smrtstats
from kloppy.infra.serializers.event.smrtstats.deserializer import (
    SmrtStatsDeserializer,
)
from kloppy.domain import (
    BallState,
    BodyPart,
    BodyPartQualifier,
    CardQualifier,
    CarryResult,
    DatasetFlag,
    DatasetType,
    Dimension,
    DuelQualifier,
    DuelResult,
    DuelType,
    EventDataset,
    FormationType,
    ImperialPitchDimensions,
    InterceptionResult,
    Orientation,
    PassResult,
    Point,
    Point3D,
    PositionType,
    Provider,
    SetPieceQualifier,
    SetPieceType,
    ShotResult,
    SubstitutionEvent,
    TakeOnResult,
    Time,
    build_coordinate_system,
    MetricPitchDimensions,
)
from kloppy.domain.models import PositionType
from kloppy.domain.models.event import (
    CardType,
    CounterAttackQualifier,
    EventType,
    GoalkeeperActionType,
    GoalkeeperQualifier,
    PassQualifier,
    PassType,
    UnderPressureQualifier,
)
from kloppy.exceptions import DeserializationError


@pytest.fixture(scope="module")
def dataset(base_dir) -> EventDataset:
    """Load SmrtStats data for Belgium - Portugal at Euro 2020"""
    dataset = smrtstats.load(
        raw_data=base_dir / "files" / "smrtstats.json",
        coordinates="smrtstats",
    )
    assert dataset.dataset_type == DatasetType.EVENT
    return dataset


class TestSmrtStatsMetadata:
    """Tests related to deserializing metadata"""

    def test_provider(self, dataset):
        """It should set the SmrtStats provider"""
        assert dataset.metadata.provider == Provider.SMRTSTATS

    def test_orientation(self, dataset):
        """It should set the action-executing-team orientation"""
        assert (
            dataset.metadata.orientation == Orientation.ACTION_EXECUTING_TEAM
        )

    def test_framerate(self, dataset):
        """It should set the frame rate to None"""
        assert dataset.metadata.frame_rate is None

    def test_teams(self, dataset):
        """It should create the teams and player objects"""
        # There should be two teams with the correct names and starting formations
        assert dataset.metadata.teams[0].name == "Orange County SC"
        assert dataset.metadata.teams[0].starting_formation == FormationType(
            "4-1-4-1"
        )
        assert dataset.metadata.teams[1].name == "New Mexico United"
        assert dataset.metadata.teams[1].starting_formation == FormationType(
            "4-1-4-1"
        )
        # The teams should have the correct players
        player = dataset.metadata.teams[0].get_player_by_id("54824")
        assert player.player_id == "54824"
        assert player.jersey_no == 5
        assert str(player) == "Tom Patrizio Brewitt"

    def test_player_position(self, dataset):
        """It should set the correct player position from the events"""
        player = dataset.metadata.teams[0].get_player_by_id("54824")

        assert player.starting_position == PositionType.RightCenterBack
        assert player.starting

        # Substituted players have a position
        sub_player = dataset.metadata.teams[0].get_player_by_id("421305")
        assert sub_player.starting_position is None
        assert sub_player.positions.last() is not None
        assert not sub_player.starting

        # Get player by position and time
        periods = dataset.metadata.periods
        period_1 = periods[0]
        period_2 = periods[1]

        home_starting_gk = dataset.metadata.teams[0].get_player_by_position(
            PositionType.Goalkeeper,
            time=Time(period=period_1, timestamp=timedelta(seconds=0)),
        )
        assert home_starting_gk.player_id == "228262"  # Colin Shutler

        home_starting_lam = dataset.metadata.teams[0].get_player_by_position(
            PositionType.RightMidfield,
            time=Time(period=period_1, timestamp=timedelta(seconds=0)),
        )
        assert home_starting_lam.player_id == "181"  # Cameron Gatlin Dunbar

        home_ending_lam = dataset.metadata.teams[0].get_player_by_position(
            PositionType.RightMidfield,
            time=Time(period=period_2, timestamp=timedelta(seconds=45 * 60)),
        )
        assert home_ending_lam.player_id == "228268"  # Bryce Everett Jamison

        away_starting_gk = dataset.metadata.teams[1].get_player_by_position(
            PositionType.Goalkeeper,
            time=Time(period=period_1, timestamp=timedelta(seconds=92)),
        )
        assert away_starting_gk.player_id == "244046"  # 'Kristopher Shakes'

    def test_pitch_dimensions(self, dataset):
        """It should set the correct pitch dimensions"""
        assert dataset.metadata.pitch_dimensions == MetricPitchDimensions(
            x_dim=Dimension(0, 105),
            y_dim=Dimension(0, 68),
            standardized=False,
        )

    def test_coordinate_system(self, dataset):
        """It should set the correct coordinate system"""
        assert dataset.metadata.coordinate_system == build_coordinate_system(
            Provider.SMRTSTATS
        )

    def test_timestamp_of_first_event_of_periods(self, dataset):
        for period in dataset.metadata.periods:
            first_event_of_period = next(
                e for e in dataset.events if e.period.id == period.id
            )
            assert first_event_of_period.timestamp <= timedelta(seconds=3)


class TestSmrtStatsEvent:
    """Generic tests related to deserializing events"""

    def test_generic_attributes(self, dataset: EventDataset):
        """Test generic event attributes"""
        event = dataset.get_event_by_id("239947304")
        assert event.event_id == "239947304"
        assert event.team.name == "Orange County SC"
        assert event.ball_owning_team.name == "Orange County SC"
        assert event.player.name == "Cameron Gatlin Dunbar"
        assert event.coordinates == Point(x=52.5, y=34.0)
        assert event.raw_event["id"] == 239947304
        assert event.period.id == 1
        assert event.timestamp == timedelta(seconds=0)
        # assert event.ball_state == BallState.ALIVE


class TestSmrtStatsPassEvent:
    def test_deserialize_all(self, dataset: EventDataset):
        """It should deserialize all pass events"""
        events = dataset.find_all("pass")
        assert len(events) == 829

    def test_open_play(self, dataset: EventDataset):
        """Verify specific attributes of simple open play pass"""
        pass_event = dataset.get_event_by_id("239947306")
        # A pass should have a result
        assert pass_event.result == PassResult.COMPLETE
        # A pass should have end coordinates
        assert pass_event.receiver_coordinates == Point(x=87.15, y=55.76)
        # A pass should have a receiver
        assert (
            pass_event.receiver_player.name == "Lyam Khonick MacKinnon Diouf"
        )

        # A pass can have set piece qualifiers
        assert pass_event.get_qualifier_value(SetPieceQualifier) is None
        # A pass can have pass qualifiers
        assert pass_event.get_qualifier_value(PassQualifier) is None

    def test_pass_qualifiers(self, dataset: EventDataset):
        """It should add pass qualifiers"""
        pass_event = dataset.get_event_by_id("239947531")
        assert pass_event.get_qualifier_values(PassQualifier) == [
            PassType.CROSS
        ]
        assert pass_event.get_qualifier_values(SetPieceQualifier) == [
            SetPieceType.CORNER_KICK
        ]

    def test_set_piece(self, dataset: EventDataset):
        """It should add set piece qualifiers to free kick passes"""
        pass_event = dataset.get_event_by_id("239947311")
        assert (
            pass_event.get_qualifier_value(SetPieceQualifier)
            == SetPieceType.FREE_KICK
        )

    def test_interception(self, dataset: EventDataset):
        """It should split interception passes into two events"""
        interception = dataset.get_event_by_id("239947350")
        assert interception.event_type == EventType.INTERCEPTION
        assert interception.result == InterceptionResult.SUCCESS

    def test_aerial_duel(self, dataset: EventDataset):
        """It should split passes that follow an aerial duel into two events"""
        duel = dataset.get_event_by_id("239947354")
        assert duel.event_type == EventType.DUEL
        assert duel.get_qualifier_values(DuelQualifier) == [
            DuelType.AERIAL,
        ]
        assert duel.result == DuelResult.WON

    def test_assists(self, dataset: EventDataset):
        """It should mark passes as assists when followed by shots/goals"""
        shot_assists = [
            e
            for e in dataset.events
            if e.event_type == EventType.PASS
            and PassType.SHOT_ASSIST in e.get_qualifier_values(PassQualifier)
        ]
        # There should be at least some shot assists
        assert len(shot_assists) > 0

        goal_assists = [
            e
            for e in dataset.events
            if e.event_type == EventType.PASS
            and PassType.ASSIST in e.get_qualifier_values(PassQualifier)
        ]
        # There should be at least some goal assists
        assert len(goal_assists) > 0


class TestSmrtStatsShotEvent:
    def test_deserialize_all(self, dataset: EventDataset):
        """It should deserialize all shot events"""
        events = dataset.find_all("shot")
        assert len(events) == 25

    def test_open_play(self, dataset: EventDataset):
        """Verify specific attributes of simple open play shot"""
        shot = dataset.get_event_by_id("239947536")
        # A shot event should have a result
        assert shot.result == ShotResult.OFF_TARGET
        # A shot event should have end coordinates
        assert shot.result_coordinates == Point3D(x=105, y=15.27, z=1.97)

    # def test_free_kick(self, dataset: EventDataset):
    #     """It should add set piece qualifiers to free kick shots"""
    #     shot = dataset.get_event_by_id("7c10ac89-738c-4e99-8c0c-f55bc5c0995e")
    #     assert (
    #         shot.get_qualifier_value(SetPieceQualifier)
    #         == SetPieceType.FREE_KICK
    #     )


class TestSmrtStatsInterceptionEvent:
    def test_deserialize_all(self, dataset: EventDataset):
        """It should deserialize all interception events"""
        events = dataset.find_all("interception")
        assert len(events) == 20

    def test_attributes(self, dataset: EventDataset):
        """Verify specific attributes of interceptions"""
        interception = dataset.get_event_by_id("239947356")
        assert interception.result == InterceptionResult.SUCCESS


class TestSmrtStatsClearanceEvent:
    """Tests related to deserializing 9/Clearance events"""

    def test_deserialize_all(self, dataset: EventDataset):
        """It should deserialize all clearance events"""
        events = dataset.find_all("clearance")
        assert len(events) == 39  # clearances + keeper sweeper

    def test_attributes(self, dataset: EventDataset):
        """Verify specific attributes of clearances"""
        clearance = dataset.get_event_by_id("239947418")
        # A clearance has no result
        assert clearance.result is None


# class TestSmrtStatsMiscontrolEvent:
#     """Tests related to deserializing 19/Miscontrol events"""
#
#     def test_deserialize_all(self, dataset: EventDataset):
#         """It should deserialize all miscontrol events"""
#         events = dataset.find_all("miscontrol")
#         assert len(events) == 22
#
#     def test_attributes(self, dataset: EventDataset):
#         """Verify specific attributes of miscontrols"""
#         miscontrol = dataset.get_event_by_id(
#             "e297def3-9907-414a-9eb5-e1269343b84d"
#         )
#         # A miscontrol has no result
#         assert miscontrol.result is None
#         # A miscontrol has no qualifiers
#         assert miscontrol.qualifiers is None
#
#     def test_aerial_duel(self, dataset: EventDataset):
#         """It should split clearances that follow an aerial duel into two events"""
#         assert True  # can happen according to the documentation, but not in the dataset


class TestSmrtStatsDribbleEvent:
    """Tests related to deserializing 17/Dribble events"""

    def test_deserialize_all(self, dataset: EventDataset):
        """It should deserialize all dribble events"""
        events = dataset.find_all("take_on")
        assert len(events) == 23

    def test_attributes(self, dataset: EventDataset):
        """Verify specific attributes of dribbles"""
        dribble = dataset.get_event_by_id("239947361")
        # A dribble should have a result
        assert dribble.result == TakeOnResult.COMPLETE

    def test_result_out(self, dataset: EventDataset):
        """The result of a dribble can be TakeOnResult.INCOMPLETE"""
        dribble = dataset.get_event_by_id("239947409")
        assert dribble.result == TakeOnResult.INCOMPLETE


# class TestSmrtStatsCarryEvent:
#     """Tests related to deserializing 22/Carry events"""
#
#     def test_deserialize_all(self, dataset: EventDataset):
#         """It should deserialize all carry events"""
#         events = dataset.find_all("carry")
#         assert len(events) == 929
#
#     def test_attributes(self, dataset: EventDataset):
#         """Verify specific attributes of carries"""
#         carry = dataset.get_event_by_id("fab6360a-cbc2-45a3-aafa-5f3ec81eb9c7")
#         # A carry is always successful
#         assert carry.result == CarryResult.COMPLETE
#         # A carry should have an end location
#         assert carry.end_coordinates == Point(21.65, 54.85)
#         # A carry should have an end timestamp
#         assert carry.end_timestamp == parse_str_ts("00:20:11.457") + timedelta(
#             seconds=1.365676
#         )


class TestSmrtStatsDuelEvent:
    """Tests related to deserializing 1/Duel events"""

    def test_deserialize_all(self, dataset: EventDataset):
        """It should deserialize all duel and 50/50 events"""
        events = dataset.find_all("duel")
        assert len(events) == 144

    def test_attributes(self, dataset: EventDataset):
        """Verify specific attributes of duels"""
        duel = dataset.get_event_by_id("239947411")
        # A duel should have a result
        assert duel.result == DuelResult.WON
        # A duel should have a duel type
        assert duel.get_qualifier_values(DuelQualifier) == [
            DuelType.GROUND,
            DuelType.TACKLE,
        ]

    def test_aerial_duel_qualifiers(self, dataset: EventDataset):
        """It should add aerial duel + loose ball qualifiers"""
        duel = dataset.get_event_by_id("239947312")
        assert duel.get_qualifier_values(DuelQualifier) == [
            DuelType.AERIAL,
        ]


class TestSmrtStatsGoalkeeperEvent:
    def test_deserialize_all(self, dataset: EventDataset):
        """It should deserialize all goalkeeper events"""
        # EFFECTIVE_SAVE events by field players are now recovery events
        events = dataset.find_all("goalkeeper")
        assert len(events) == 9

        # Field player saves should be recovery events
        recovery_events = dataset.find_all("recovery")
        # Original recovery events + field player EFFECTIVE_SAVE events
        assert len(recovery_events) == 6

    def test_save(self, dataset: EventDataset):
        """It should deserialaize goalkeeper saves"""
        # A save should be deserialized as a goalkeeper event
        save = dataset.get_event_by_id("239947546")
        assert save.get_qualifier_value(GoalkeeperQualifier) == (
            GoalkeeperActionType.SAVE
        )

    def test_all_goalkeeper_events_by_goalkeepers(self, dataset: EventDataset):
        """All goalkeeper events should be performed by actual goalkeepers"""
        goalkeeper_events = dataset.find_all("goalkeeper")
        for event in goalkeeper_events:
            current_position = event.player.positions.last()

            assert current_position == PositionType.Goalkeeper, (
                f"Goalkeeper event {event.event_id} was performed by "
                f"{event.player.name} who is not a goalkeeper (position: {current_position})"
            )


class TestSmrtStatsSubstitutionEvent:
    """Tests related to deserializing 18/Substitution events"""

    def test_deserialize_all(self, dataset: EventDataset):
        """It should deserialize all substitution events"""
        events = dataset.find_all("substitution")
        assert len(events) == 10

        first_sub_event = events[0]
        assert first_sub_event.player == dataset.metadata.teams[
            0
        ].get_player_by_id("182350")
        assert first_sub_event.replacement_player == dataset.metadata.teams[
            0
        ].get_player_by_id("356")


class TestsSmrtStatsBadBehaviourEvent:
    """Tests related to deserializing 22/Bad Behaviour events"""

    def test_deserialize_all(self, dataset: EventDataset):
        """It should create a card event for each card given"""
        events = dataset.find_all("card")
        assert len(events) == 9

        for event in events:
            assert event.card_type == CardType.FIRST_YELLOW


class TestSmrtStatsFoulCommittedEvent:
    """Tests related to deserializing 2/Foul Committed events"""

    def test_deserialize_all(self, dataset: EventDataset):
        """It should deserialize all foul committed events"""
        events = dataset.find_all("foul_committed")
        assert len(events) == 33


# class TestSmrtStatsRecoveryEvent:
#     """Tests related to deserializing 23/Recovery events"""
#
#     def test_deserialize_successful(self, dataset: EventDataset):
#         """It should deserialize all successful ball recovery events"""
#         events = dataset.find_all("recovery")
#         assert len(events) == 93
#
#     def test_deserialize_failed(self, dataset: EventDataset):
#         """It should deserialize all failed ball recovery events as loose ball duels"""
#         failed_recovery = dataset.get_event_by_id(
#             "0df4c1d6-1c4a-407b-876d-d9ac80fd7eee"
#         )
#         assert failed_recovery.event_type == EventType.DUEL
#         assert failed_recovery.get_qualifier_values(DuelQualifier) == [
#             DuelType.LOOSE_BALL,
#         ]
#         assert failed_recovery.result == DuelResult.LOST


# class TestSmrtStatsTacticalShiftEvent:
#     """Tests related to deserializing 34/Tactical Shift events"""
#
#     def test_deserialize_all(self, dataset: EventDataset):
#         """It should deserialize all tactical shift events"""
#         events = dataset.find_all("formation_change")
#         assert len(events) == 2
#
#     def test_attributes(self, dataset: EventDataset):
#         """Verify specific attributes of tactical shift events"""
#         formation_change = dataset.get_event_by_id(
#             "983cdd00-6f7f-4d62-bfc2-74e4e5b0137f"
#         )
#         assert formation_change.formation_type == FormationType("4-3-3")
#
#     def test_player_position(self, base_dir):
#         dataset = smrtstats.load(
#             lineup_data=base_dir / "files/smrtstats_lineup.json",
#             event_data=base_dir / "files/smrtstats_event.json",
#         )
#
#         for item in dataset.aggregate("minutes_played", include_position=True):
#             print(
#                 f"{item.player} {item.player.player_id}- {item.start_time} - {item.end_time} - {item.duration} - {item.position}"
#             )
#
#         home_team, away_team = dataset.metadata.teams
#         period1, period2 = dataset.metadata.periods
#
#         player = home_team.get_player_by_id(6379)
#         assert player.positions.ranges() == [
#             (
#                 period1.start_time,
#                 period2.start_time,
#                 PositionType.RightMidfield,
#             ),
#             (
#                 period2.start_time,
#                 period2.end_time,
#                 PositionType.RightBack,
#             ),
#         ]
#
#         # This player gets a new position 30 sec after he gets on the pitch, these two positions must be merged
#         player = away_team.get_player_by_id(6935)
#         assert player.positions.ranges() == [
#             (
#                 period2.start_time + timedelta(seconds=1362.254),
#                 period2.end_time,
#                 PositionType.LeftMidfield,
#             )
#         ]


class TestSmrtStatsRelativeCoordRecovery:
    """Smrtstats emits ``relative_coord_*`` as null when an event sits on
    a pitch boundary (x=0/105 or y=0/68); the absolute ``coord_*`` is
    still populated. The parser recovers the missing relative value from
    the absolute, using the team's attacking-direction frame detected
    from any other non-null coord pair on the same event.
    """

    def test_attack_direction_detection_mirrored(self):
        """A throw-in whose relative_coord_x is mirrored relative to
        coord_x must be flagged as a mirrored-frame event."""
        from kloppy.infra.serializers.event.smrtstats.deserializer import (
            _attack_direction_mirrored,
        )

        raw = {
            "coord_x": 69.2,
            "coord_y": 0.0,
            "relative_coord_x": 35.8,
            "relative_coord_y": None,
        }
        assert _attack_direction_mirrored(raw) is True

    def test_attack_direction_detection_direct(self):
        """A pass whose relative_coord_x matches coord_x must be flagged
        as a direct-frame event."""
        from kloppy.infra.serializers.event.smrtstats.deserializer import (
            _attack_direction_mirrored,
        )

        raw = {
            "coord_x": 3.47,
            "coord_y": 19.24,
            "coord_x_destination": 18.06,
            "coord_y_destination": 0.0,
            "relative_coord_x": 3.47,
            "relative_coord_y": 19.24,
            "relative_coord_x_destination": 18.06,
            "relative_coord_y_destination": None,
        }
        assert _attack_direction_mirrored(raw) is False

    def test_attack_direction_detection_unknown(self):
        """When every relative is null or every pair sits on the pitch
        midpoint, orientation cannot be determined."""
        from kloppy.infra.serializers.event.smrtstats.deserializer import (
            _attack_direction_mirrored,
        )

        all_null = {
            "coord_x": 0.0,
            "coord_y": 0.0,
            "relative_coord_x": None,
            "relative_coord_y": None,
        }
        assert _attack_direction_mirrored(all_null) is None

        midpoint = {
            "coord_x": 52.5,
            "coord_y": 34.0,
            "relative_coord_x": 52.5,
            "relative_coord_y": 34.0,
        }
        assert _attack_direction_mirrored(midpoint) is None

    def test_resolve_relative_coord_passthrough(self):
        """A populated relative coord must be returned unchanged."""
        from kloppy.infra.serializers.event.smrtstats.deserializer import (
            _resolve_relative_coord,
        )

        raw = {"relative_coord_x": 42.0, "coord_x": 63.0}
        assert _resolve_relative_coord(raw, "x", is_destination=False) == 42.0

    def test_resolve_relative_coord_recovers_mirrored(self):
        """Null relative on a mirrored-frame event must recover as
        ``pitch_dim - coord_*``."""
        from kloppy.infra.serializers.event.smrtstats.deserializer import (
            _resolve_relative_coord,
        )

        # Mirrored team (relative_x=35.8 mirrors coord_x=69.2); start_y is null.
        raw = {
            "coord_x": 69.2,
            "coord_y": 0.0,
            "relative_coord_x": 35.8,
            "relative_coord_y": None,
        }
        assert _resolve_relative_coord(raw, "y", is_destination=False) == 68.0

    def test_resolve_relative_coord_recovers_direct(self):
        """Null relative on a direct-frame event must recover as
        ``coord_*`` itself."""
        from kloppy.infra.serializers.event.smrtstats.deserializer import (
            _resolve_relative_coord,
        )

        # Direct team (relative_x matches coord_x); destination_y is null at
        # the y=0 sideline.
        raw = {
            "coord_x": 3.47,
            "coord_y": 19.24,
            "coord_x_destination": 18.06,
            "coord_y_destination": 0.0,
            "relative_coord_x": 3.47,
            "relative_coord_y": 19.24,
            "relative_coord_x_destination": 18.06,
            "relative_coord_y_destination": None,
        }
        assert _resolve_relative_coord(raw, "y", is_destination=True) == 0.0

    def test_resolve_relative_coord_fallback_when_absolute_missing(self):
        """When both relative and absolute are missing, fall back to 0
        (matches prior behaviour for malformed events)."""
        from kloppy.infra.serializers.event.smrtstats.deserializer import (
            _resolve_relative_coord,
        )

        raw = {"relative_coord_x": None, "coord_x": None}
        assert _resolve_relative_coord(raw, "x", is_destination=False) == 0

    def test_throwin_start_y_recovered_on_mirrored_team(
        self, dataset: EventDataset
    ):
        """Anchor: event 239947349 is a throw-in on a mirrored-frame team
        with null relative_coord_y. Absolute coord_y=0 -> recovered to 68
        (the sideline on the mirrored side)."""
        throw_in = dataset.get_event_by_id("239947349")
        assert throw_in is not None
        assert SetPieceType.THROW_IN in throw_in.get_qualifier_values(
            SetPieceQualifier
        )
        # x is left as the raw relative_coord_x (no longer mirrored).
        assert throw_in.coordinates.x == pytest.approx(35.8)
        assert throw_in.coordinates.y == pytest.approx(68.0)

    def test_cross_destination_x_recovered_on_mirrored_team(
        self, dataset: EventDataset
    ):
        """Anchor: event 239947395 is a pass on a mirrored-frame team
        with null relative_coord_x_destination. Absolute
        coord_x_destination=0 -> recovered to 105 (the byline opposite
        the team's own goal)."""
        event = dataset.get_event_by_id("239947395")
        assert event is not None
        assert event.event_type == EventType.PASS
        assert event.receiver_coordinates.x == pytest.approx(105.0)
        assert event.receiver_coordinates.y == pytest.approx(53.38)

    def test_destination_y_recovered_on_direct_team(
        self, dataset: EventDataset
    ):
        """Anchor: event 239947520 is a pass on a direct-frame team with
        null relative_coord_y_destination. Absolute coord_y_destination=0
        -> recovered to 0 (the sideline on the direct side)."""
        event = dataset.get_event_by_id("239947520")
        assert event is not None
        assert event.event_type == EventType.PASS
        assert event.receiver_coordinates.y == pytest.approx(0.0)

    def test_destination_y_recovered_on_mirrored_team(
        self, dataset: EventDataset
    ):
        """Anchor: event 239947654 is a pass on a mirrored-frame team
        with null relative_coord_y_destination. Absolute
        coord_y_destination=0 -> recovered to 68 (the sideline on the
        mirrored side). This is the case the legacy ``if x else 0``
        fallback handled incorrectly."""
        event = dataset.get_event_by_id("239947654")
        assert event is not None
        assert event.event_type == EventType.PASS
        assert event.receiver_coordinates.y == pytest.approx(68.0)

    def test_every_throwin_starts_on_a_sideline(self, dataset: EventDataset):
        """Sanity guard: a throw-in is taken from a sideline, so its
        start y must be 0 or 68 in the smrtstats coord system. The
        legacy bug defaulted null ``relative_coord_y`` to 0, which
        happened to satisfy this on direct-frame teams but produced
        midfield coords if any other regression slipped in. To also
        catch regressions where every throw-in collapses to a single
        sideline, the fixture must contain throw-ins from both."""
        throw_ins = [
            e
            for e in dataset.events
            if e.event_type == EventType.PASS
            and SetPieceType.THROW_IN
            in e.get_qualifier_values(SetPieceQualifier)
        ]
        assert throw_ins, "fixture should contain throw-ins"
        sidelines = set()
        for tin in throw_ins:
            assert tin.coordinates.y in (0.0, 68.0), (
                f"throw-in {tin.event_id} starts at y={tin.coordinates.y}, "
                f"not on a sideline"
            )
            sidelines.add(tin.coordinates.y)
        assert sidelines == {0.0, 68.0}, (
            "expected throw-ins on both sidelines; a single-sideline-only "
            "result usually means null relative_coord_y is silently "
            "defaulting to 0 instead of being recovered"
        )

    def test_no_throwin_crosses_the_pitch_laterally(
        self, dataset: EventDataset
    ):
        """The reported TAS-3065 symptom: throw-ins visualised as
        spanning the full width of the pitch (thrower on one sideline,
        receiver near the opposite sideline). In reality the thrower
        and receiver are always on the same lateral half of the pitch
        — across the full fixture no throw-in's receiver lands beyond
        the y=34 midline relative to the thrower's sideline. The
        legacy null-default produced exactly the cross-pitch arrow
        whenever a mirrored-frame team threw in: thrower forced to
        y=0 while the receiver kept its real (e.g. y≈60) coordinate.
        """
        throw_ins = [
            e
            for e in dataset.events
            if e.event_type == EventType.PASS
            and SetPieceType.THROW_IN
            in e.get_qualifier_values(SetPieceQualifier)
            and e.receiver_coordinates is not None
        ]
        assert throw_ins, "fixture should contain throw-ins with receivers"
        for tin in throw_ins:
            start_y = tin.coordinates.y
            recv_y = tin.receiver_coordinates.y
            if start_y == 0.0:
                assert recv_y < 34.0, (
                    f"throw-in {tin.event_id} from y=0 to y={recv_y} "
                    f"appears to cross the pitch — classic null "
                    f"relative_coord_y bug"
                )
            elif start_y == 68.0:
                assert recv_y > 34.0, (
                    f"throw-in {tin.event_id} from y=68 to y={recv_y} "
                    f"appears to cross the pitch — classic null "
                    f"relative_coord_y bug"
                )

    def test_no_cross_ends_in_attackers_defensive_half(
        self, dataset: EventDataset
    ):
        """Sanity guard: under ``Orientation.ACTION_EXECUTING_TEAM`` the
        attacking team plays towards x=105. A cross is by definition
        delivered into the opponent's box near that byline; it cannot
        end up deep in the attacker's own defensive half. The legacy
        bug defaulted null ``relative_coord_x_destination`` to 0 (own
        goal line), so any cross with a null destination on a mirrored
        team appeared to travel from x≈75 back to x=0. This guard
        flags that exact regression."""
        crosses = [
            e
            for e in dataset.events
            if e.event_type == EventType.PASS
            and PassType.CROSS in e.get_qualifier_values(PassQualifier)
        ]
        assert crosses, "fixture should contain crosses"
        for cross in crosses:
            if cross.receiver_coordinates is None:
                continue
            assert cross.receiver_coordinates.x >= 52.5, (
                f"cross {cross.event_id} starts at x={cross.coordinates.x} "
                f"but ends at x={cross.receiver_coordinates.x} — back in "
                f"the attacker's defensive half (looks like the null "
                f"relative_coord_x_destination bug)"
            )

    def test_null_relative_coords_are_recovered_across_fixture(
        self, dataset: EventDataset
    ):
        """Across the full fixture, every pass/start with a null
        ``relative_coord_*`` and a populated ``coord_*`` must end up
        with the recovered value the helper would compute (i.e. the
        absolute itself for direct-frame teams, ``pitch_dim - absolute``
        for mirrored-frame teams) — never the legacy zero default. At
        least one event must be recovered to a non-zero value to prove
        the recovery code path is exercised by real data."""
        from kloppy.infra.serializers.event.smrtstats.deserializer import (
            _attack_direction_mirrored,
        )

        recovered_nonzero = 0
        for event in dataset.events:
            raw = event.raw_event
            mirrored = _attack_direction_mirrored(raw)
            for is_destination, point in (
                (False, event.coordinates),
                (
                    True,
                    getattr(event, "receiver_coordinates", None),
                ),
            ):
                if point is None:
                    continue
                suffix = "_destination" if is_destination else ""
                for axis, dim in (("x", 105), ("y", 68)):
                    if raw.get(f"relative_coord_{axis}{suffix}") is not None:
                        continue
                    absolute = raw.get(f"coord_{axis}{suffix}")
                    if absolute is None:
                        continue
                    if mirrored is None:
                        expected = absolute
                    elif mirrored:
                        expected = dim - absolute
                    else:
                        expected = absolute
                    actual = getattr(point, axis)
                    assert actual == pytest.approx(expected), (
                        f"event {event.event_id}: {axis}{suffix} "
                        f"expected {expected} (absolute={absolute}, "
                        f"mirrored={mirrored}) but got {actual}"
                    )
                    if expected != 0:
                        recovered_nonzero += 1
        assert recovered_nonzero > 0, (
            "fixture should exercise the recovery branch; if this fails the "
            "fixture changed or the helper is being short-circuited"
        )


class TestSmrtStatsCreatePeriods:
    """Unit tests for SmrtStatsDeserializer.create_periods.

    Kloppy assigns Period 1/2 to regulation halves, Period 3/4 to the two
    halves of extra time and Period 5 to the penalty shootout.
    """

    def test_normal_match(self):
        """first_half_markers -> P1, second_half_markers -> P2, no P5."""
        raw = {
            "first_half_markers": [
                {"action_id": 1, "second": 0.0},
                {"action_id": 74, "second": 2700.0},
            ],
            "second_half_markers": [
                {"action_id": 75, "second": 2750.0},
                {"action_id": 89, "second": 5500.0},
            ],
        }
        periods = SmrtStatsDeserializer.create_periods(raw)
        assert [p.id for p in periods] == [1, 2]
        assert periods[0].start_timestamp == timedelta(seconds=0)
        assert periods[0].end_timestamp == timedelta(seconds=2700)
        assert periods[1].start_timestamp == timedelta(seconds=2750)
        assert periods[1].end_timestamp == timedelta(seconds=5500)

    def test_shootout_quirk_both_halves_in_first(self):
        """Both regulation halves in first_half_markers; shootout in second.

        Observed on matches 720080 (Argentinos vs Barcelona SC) and 720083
        (Tolima vs Táchira) — Copa Libertadores qualifiers that went
        straight from regulation to penalties.
        """
        raw = {
            "first_half_markers": [
                {"action_id": 1, "second": 0.0},
                {"action_id": 2, "second": 100.0},
                {"action_id": 74, "second": 2996.0},
                {"action_id": 75, "second": 2996.0},
                {"action_id": 2, "second": 4000.0},
            ],
            "second_half_markers": [
                {"action_id": 74, "second": 6026.0},
                {"action_id": 65, "second": 6100.0},  # shootout goal
                {"action_id": 89, "second": 6686.0},
            ],
        }
        periods = SmrtStatsDeserializer.create_periods(raw)
        assert [p.id for p in periods] == [1, 2, 5]

        assert periods[0].start_timestamp == timedelta(seconds=0)
        assert periods[0].end_timestamp == timedelta(seconds=2996)

        assert periods[1].start_timestamp == timedelta(seconds=2996)
        assert periods[1].end_timestamp == timedelta(seconds=6026)

        assert periods[2].start_timestamp == timedelta(seconds=6026)
        assert periods[2].end_timestamp == timedelta(seconds=6686)

    def test_extra_time_plus_shootout(self):
        """Extra time followed by a penalty shootout (5 periods).

        Modeled after match 671052 (Stockport vs Leyton Orient, EFL L1
        play-off SF 2nd leg). SmrtStats's ET layout puts every 2nd-half,
        ET and shootout marker into second_half_markers with action_ids
        1/75/81/85/74/89 driving the boundaries.
        """
        raw = {
            "first_half_markers": [
                {"action_id": 1, "second": 0.0},
                {"action_id": 2, "second": 500.0},
            ],
            "second_half_markers": [
                {"action_id": 74, "second": 2957.0},
                {"action_id": 75, "second": 2957.0},
                {"action_id": 2, "second": 4000.0},
                {"action_id": 74, "second": 5959.0},
                {"action_id": 81, "second": 5959.0},
                {"action_id": 2, "second": 6500.0},
                {"action_id": 74, "second": 6865.0},
                {"action_id": 85, "second": 6865.0},
                {"action_id": 2, "second": 7500.0},
                {"action_id": 74, "second": 7832.0},
                {"action_id": 65, "second": 7900.0},  # shootout goal
                {"action_id": 89, "second": 8195.0},
            ],
        }
        periods = SmrtStatsDeserializer.create_periods(raw)
        assert [p.id for p in periods] == [1, 2, 3, 4, 5]
        assert periods[0].start_timestamp == timedelta(seconds=0)
        assert periods[0].end_timestamp == timedelta(seconds=2957)
        assert periods[1].start_timestamp == timedelta(seconds=2957)
        assert periods[1].end_timestamp == timedelta(seconds=5959)
        assert periods[2].start_timestamp == timedelta(seconds=5959)
        assert periods[2].end_timestamp == timedelta(seconds=6865)
        assert periods[3].start_timestamp == timedelta(seconds=6865)
        assert periods[3].end_timestamp == timedelta(seconds=7832)
        assert periods[4].start_timestamp == timedelta(seconds=7832)
        assert periods[4].end_timestamp == timedelta(seconds=8195)

    def test_extra_time_no_shootout(self):
        """ET that settles the match produces 4 periods (no P5)."""
        raw = {
            "first_half_markers": [
                {"action_id": 1, "second": 0.0},
            ],
            "second_half_markers": [
                {"action_id": 75, "second": 2900.0},
                {"action_id": 81, "second": 5800.0},
                {"action_id": 85, "second": 6700.0},
                {"action_id": 89, "second": 7600.0},
            ],
        }
        periods = SmrtStatsDeserializer.create_periods(raw)
        assert [p.id for p in periods] == [1, 2, 3, 4]
        assert periods[3].start_timestamp == timedelta(seconds=6700)
        assert periods[3].end_timestamp == timedelta(seconds=7600)

    def test_empty_input(self):
        assert SmrtStatsDeserializer.create_periods({}) == []
        assert (
            SmrtStatsDeserializer.create_periods(
                {"first_half_markers": [], "second_half_markers": []}
            )
            == []
        )

    def test_half_time_stamped_after_the_restart(self):
        """HALF_TIME arriving after SECOND_HALF still ends the first half.

        SmrtStats does not guarantee that HALF_TIME (74) precedes the
        SECOND_HALF (75) marker it pairs with. Matches 683623
        (Lens-Nantes), 687100 (Cesena-Padova) and 686513 (Cardiff-Bolton)
        stamp it 1-7 seconds later. Because there is only one HALF_TIME in
        the file, reading it as the second half's end collapsed P2 to a
        couple of seconds and pushed the real second half into a phantom
        shootout period.
        """
        raw = {
            "first_half_markers": [
                {"action_id": 1, "second": 0.0},
                {"action_id": 2, "second": 100.0},
                {"action_id": 2, "second": 2758.0},
                {"action_id": 75, "second": 2760.0},
            ],
            "second_half_markers": [
                {"action_id": 74, "second": 2761.0},
                {"action_id": 2, "second": 2762.0},
                {"action_id": 2, "second": 5700.0},
                {"action_id": 89, "second": 5785.0},
            ],
        }
        periods = SmrtStatsDeserializer.create_periods(raw)
        assert [p.id for p in periods] == [1, 2]
        assert periods[0].start_timestamp == timedelta(seconds=0)
        assert periods[0].end_timestamp == timedelta(seconds=2760)
        assert periods[1].start_timestamp == timedelta(seconds=2760)
        assert periods[1].end_timestamp == timedelta(seconds=5785)

    def test_half_time_stamped_after_the_restart_with_trailing_play(self):
        """The first half's last touches may share the restart's second.

        Match 683623 stamps three first-half events (a duel, a misplaced
        pass and a substitution) at 2760.0, the same second as the
        SECOND_HALF marker, with HALF_TIME at 2761.0. So "no markers at
        all between the restart and HALF_TIME" is too strict a test -- the
        question is whether any *play* happened strictly between them.
        """
        raw = {
            "first_half_markers": [
                {"action_id": 1, "second": 0.0},
                {"action_id": 2, "second": 100.0},
                {"action_id": 75, "second": 2760.0},
                {"action_id": 11, "second": 2760.0},
                {"action_id": 77, "second": 2760.0},
                {"action_id": 26, "second": 2760.0},
            ],
            "second_half_markers": [
                {"action_id": 74, "second": 2761.0},
                {"action_id": 33, "second": 2762.0},
                {"action_id": 2, "second": 5700.0},
                {"action_id": 89, "second": 5785.0},
            ],
        }
        periods = SmrtStatsDeserializer.create_periods(raw)
        assert [p.id for p in periods] == [1, 2]
        assert periods[0].end_timestamp == timedelta(seconds=2760)
        assert periods[1].start_timestamp == timedelta(seconds=2760)
        assert periods[1].end_timestamp == timedelta(seconds=5785)

    def test_late_half_time_does_not_trigger_a_shootout(self):
        """A late HALF_TIME must not be read as a shootout whistle.

        This is what actually loses the data: every MGP ingest loads with
        ``exclude_penalty_shootouts=True``, so a phantom P5 covering the
        real second half is dropped on the floor rather than merely
        mislabelled.
        """
        raw = {
            "first_half_markers": [
                {"action_id": 1, "second": 0.0},
                {"action_id": 2, "second": 1000.0},
                {"action_id": 75, "second": 2866.0},
            ],
            "second_half_markers": [
                {"action_id": 74, "second": 2873.0},
                {"action_id": 2, "second": 3000.0},
                {"action_id": 65, "second": 4000.0},
                {"action_id": 2, "second": 5900.0},
                {"action_id": 89, "second": 5921.0},
            ],
        }
        periods = SmrtStatsDeserializer.create_periods(raw)
        assert 5 not in [p.id for p in periods]
        second_half = periods[1]
        assert second_half.end_timestamp - second_half.start_timestamp > (
            timedelta(minutes=40)
        )

    def test_genuine_shootout_survives_a_late_half_time(self):
        """A file can carry both quirks: the late twin AND a real shootout.

        The late twin sits right on top of the restart with no play in
        between; the shootout whistle has a full half of play before it.
        Only the latter may open P5.
        """
        raw = {
            "first_half_markers": [
                {"action_id": 1, "second": 0.0},
                {"action_id": 2, "second": 1000.0},
                {"action_id": 75, "second": 2900.0},
            ],
            "second_half_markers": [
                {"action_id": 74, "second": 2905.0},  # late twin
                {"action_id": 2, "second": 3000.0},
                {"action_id": 2, "second": 5800.0},
                {"action_id": 74, "second": 5900.0},  # shootout whistle
                {"action_id": 65, "second": 6000.0},
                {"action_id": 89, "second": 6300.0},
            ],
        }
        periods = SmrtStatsDeserializer.create_periods(raw)
        assert [p.id for p in periods] == [1, 2, 5]
        assert periods[0].end_timestamp == timedelta(seconds=2900)
        assert periods[1].start_timestamp == timedelta(seconds=2900)
        assert periods[1].end_timestamp == timedelta(seconds=5900)
        assert periods[2].start_timestamp == timedelta(seconds=5900)
        assert periods[2].end_timestamp == timedelta(seconds=6300)

    def test_late_half_time_with_the_lineup_dump_in_the_gap(self):
        """A stray marker in the gap must not rescue the late HALF_TIME.

        Match 683634 (Paris FC-PSG) writes twelve second-half position
        markers at 2761, between the SECOND_HALF marker at 2760 and the
        HALF_TIME at 2762. There *are* markers in between, so adjacency
        alone no longer identifies the late twin -- but a shootout has no
        open play, and a whole half of it follows.
        """
        raw = {
            "first_half_markers": [
                {"action_id": 1, "second": 0.0},
                {"action_id": 2, "second": 1000.0},
                {"action_id": 75, "second": 2760.0},
                {"action_id": 4, "second": 2761.0},
                {"action_id": 9, "second": 2761.0},
                {"action_id": 12, "second": 2761.0},
            ],
            "second_half_markers": [
                {"action_id": 74, "second": 2762.0},
                {"action_id": 2, "second": 2800.0},
                {"action_id": 25, "second": 4000.0},
                {"action_id": 2, "second": 5700.0},
                {"action_id": 89, "second": 5768.0},
            ],
        }
        periods = SmrtStatsDeserializer.create_periods(raw)
        assert [p.id for p in periods] == [1, 2]
        assert periods[0].end_timestamp == timedelta(seconds=2760)
        assert periods[1].end_timestamp == timedelta(seconds=5768)

    def test_late_half_time_with_open_play_in_the_gap(self):
        """Play inside the gap still does not make it a shootout whistle.

        Match 723447 (Real Monarchs-The Town) restarts at 2767, plays on
        (passes, a clearance, an aerial duel) and only then stamps a
        second HALF_TIME at 2778. Whatever landed in the gap, ~50 minutes
        of open play follows, and a penalty shootout contains none.
        """
        raw = {
            "first_half_markers": [
                {"action_id": 1, "second": 0.0},
                {"action_id": 2, "second": 1000.0},
            ],
            "second_half_markers": [
                {"action_id": 75, "second": 2767.0},
                {"action_id": 74, "second": 2767.0},
                {"action_id": 26, "second": 2771.0},
                {"action_id": 115, "second": 2774.0},
                {"action_id": 30, "second": 2776.0},
                {"action_id": 74, "second": 2778.0},
                {"action_id": 2, "second": 3000.0},
                {"action_id": 2, "second": 5700.0},
                {"action_id": 89, "second": 5742.0},
            ],
        }
        periods = SmrtStatsDeserializer.create_periods(raw)
        assert [p.id for p in periods] == [1, 2]
        assert periods[0].end_timestamp == timedelta(seconds=2767)
        assert periods[1].start_timestamp == timedelta(seconds=2767)
        assert periods[1].end_timestamp == timedelta(seconds=5742)

    def test_shootout_recognised_with_no_open_play_after_it(self):
        """The mirror image: a short, play-free tail *is* a shootout.

        Same shape as the test above but the tail is kicks, saves and
        goals rather than open play, so P5 must appear.
        """
        raw = {
            "first_half_markers": [
                {"action_id": 1, "second": 0.0},
                {"action_id": 2, "second": 1000.0},
            ],
            "second_half_markers": [
                {"action_id": 75, "second": 2767.0},
                {"action_id": 74, "second": 2767.0},
                {"action_id": 2, "second": 3000.0},
                {"action_id": 2, "second": 5700.0},
                {"action_id": 74, "second": 5800.0},
                {"action_id": 65, "second": 5850.0},  # shootout goal
                {"action_id": 70, "second": 5900.0},  # shootout shot
                {"action_id": 71, "second": 5950.0},  # shootout save
                {"action_id": 89, "second": 6100.0},
            ],
        }
        periods = SmrtStatsDeserializer.create_periods(raw)
        assert [p.id for p in periods] == [1, 2, 5]
        assert periods[1].end_timestamp == timedelta(seconds=5800)
        assert periods[2].start_timestamp == timedelta(seconds=5800)
        assert periods[2].end_timestamp == timedelta(seconds=6100)

    def test_period_never_ends_before_its_last_event(self):
        """Backstop invariant, independent of which marker was misplaced.

        Here MATCH_END is stamped before the last event of the match. The
        period end is pushed out to that event rather than leaving it
        outside every period.
        """
        raw = {
            "first_half_markers": [
                {"action_id": 1, "second": 0.0},
                {"action_id": 2, "second": 100.0},
                {"action_id": 74, "second": 2700.0},
            ],
            "second_half_markers": [
                {"action_id": 75, "second": 2750.0},
                {"action_id": 2, "second": 3000.0},
                {"action_id": 89, "second": 5000.0},
                {"action_id": 2, "second": 5200.0},
            ],
        }
        periods = SmrtStatsDeserializer.create_periods(raw)
        assert [p.id for p in periods] == [1, 2]
        assert periods[1].end_timestamp == timedelta(seconds=5200)

    def test_extra_time_marker_lists_deduplicated(self):
        """first_extra_time_markers is a duplicate subset of
        second_half_markers; pooling both must not produce a sixth period
        or shift boundaries.
        """
        ET1_EVENT = {"id": 1000, "action_id": 2, "second": 6000.0}
        raw = {
            "first_half_markers": [
                {"id": 1, "action_id": 1, "second": 0.0},
            ],
            "second_half_markers": [
                {"id": 10, "action_id": 75, "second": 2900.0},
                {"id": 20, "action_id": 81, "second": 5900.0},
                ET1_EVENT,
                {"id": 30, "action_id": 85, "second": 6800.0},
                {"id": 40, "action_id": 89, "second": 7700.0},
            ],
            "first_extra_time_markers": [ET1_EVENT],
        }
        periods = SmrtStatsDeserializer.create_periods(raw)
        assert [p.id for p in periods] == [1, 2, 3, 4]


class TestSmrtStatsShootoutMatch:
    """Integration tests against a trimmed real-world shootout fixture
    (derived from match 720080, Argentinos Juniors vs Barcelona SC)."""

    @pytest.fixture(scope="class")
    def shootout_dataset(self, base_dir) -> EventDataset:
        return smrtstats.load(
            raw_data=base_dir / "files" / "smrtstats_shootout.json",
            coordinates="smrtstats",
        )

    @pytest.fixture(scope="class")
    def shootout_dataset_excluded(self, base_dir) -> EventDataset:
        return smrtstats.load(
            raw_data=base_dir / "files" / "smrtstats_shootout.json",
            coordinates="smrtstats",
            exclude_penalty_shootouts=True,
        )

    def test_periods_include_shootout(self, shootout_dataset):
        """Three periods: two regulation halves + penalty shootout (P5)."""
        period_ids = [p.id for p in shootout_dataset.metadata.periods]
        assert period_ids == [1, 2, 5]

    def test_period_boundaries(self, shootout_dataset):
        """Period timestamps align with the raw SmrtStats markers."""
        p1, p2, p5 = shootout_dataset.metadata.periods
        # First half: action_id=1 at 0s, HALF_TIME at 2996s.
        assert p1.start_timestamp == timedelta(seconds=0)
        # Second half: starts at the SECOND_HALF marker (2996s), ends at
        # the last regulation event (5995s in the raw file).
        assert p2.start_timestamp == timedelta(seconds=2996)
        # Penalty shootout bounds from second_half_markers.
        assert p5.start_timestamp == timedelta(seconds=6026)
        assert p5.end_timestamp == timedelta(seconds=6686)

    def test_events_routed_by_period(self, shootout_dataset):
        """Every shootout event lands in Period 5; regulation events do not."""
        shootout_events = [
            e for e in shootout_dataset.events if e.period.id == 5
        ]
        assert len(shootout_events) > 0
        for event in shootout_events:
            absolute_second = (
                event.period.start_timestamp.total_seconds()
                + event.timestamp.total_seconds()
            )
            assert 6026 <= absolute_second <= 6686

    def test_exclude_penalty_shootouts(
        self, shootout_dataset, shootout_dataset_excluded
    ):
        """exclude_penalty_shootouts strips Period 5 and its events."""
        period_ids = [p.id for p in shootout_dataset_excluded.metadata.periods]
        assert period_ids == [1, 2]
        assert all(e.period.id != 5 for e in shootout_dataset_excluded.events)
        # The excluded dataset should have strictly fewer events.
        assert len(shootout_dataset_excluded.events) < len(
            shootout_dataset.events
        )

    def test_shootout_shots_at_penalty_spots(self, shootout_dataset):
        """Every P5 shot lands at one of the two penalty-spot
        x-coordinates (≈ 92.92 or ≈ 12.08 on the 105 m-long pitch)."""
        shootout_shots = [
            e
            for e in shootout_dataset.events
            if e.event_type == EventType.SHOT and e.period.id == 5
        ]
        assert len(shootout_shots) > 0
        for shot in shootout_shots:
            assert shot.coordinates.x in (
                pytest.approx(92.92),
                pytest.approx(12.08),
            ), f"shot {shot.event_id} at x={shot.coordinates.x}"
            assert shot.coordinates.y == pytest.approx(34.0)


class TestSmrtStatsExtraTimeMatch:
    """Integration tests against a trimmed ET + shootout fixture derived
    from match 671052 (Stockport County vs Leyton Orient, EFL L1 play-off
    semi-final 2nd leg 2025-05-14 — went to extra time and penalties)."""

    @pytest.fixture(scope="class")
    def et_dataset(self, base_dir) -> EventDataset:
        return smrtstats.load(
            raw_data=base_dir / "files" / "smrtstats_extra_time.json",
            coordinates="smrtstats",
        )

    @pytest.fixture(scope="class")
    def et_dataset_excluded(self, base_dir) -> EventDataset:
        return smrtstats.load(
            raw_data=base_dir / "files" / "smrtstats_extra_time.json",
            coordinates="smrtstats",
            exclude_penalty_shootouts=True,
        )

    def test_five_periods(self, et_dataset):
        """Regulation (P1+P2), extra time (P3+P4) and shootout (P5)."""
        assert [p.id for p in et_dataset.metadata.periods] == [1, 2, 3, 4, 5]

    def test_period_boundaries(self, et_dataset):
        """Period boundaries align with the 1/75/81/85/74/89 markers."""
        p1, p2, p3, p4, p5 = et_dataset.metadata.periods
        # FIRST_HALF at 0s, HALF_TIME at 2957s.
        assert p1.start_timestamp == timedelta(seconds=0)
        assert p1.end_timestamp == timedelta(seconds=2957)
        # SECOND_HALF at 2957s, ET1 start at 5959s.
        assert p2.start_timestamp == timedelta(seconds=2957)
        assert p2.end_timestamp == timedelta(seconds=5959)
        # ET1 start at 5959s, ET2 start at 6865s.
        assert p3.start_timestamp == timedelta(seconds=5959)
        assert p3.end_timestamp == timedelta(seconds=6865)
        # ET2 start at 6865s, final HALF_TIME at 7832s.
        assert p4.start_timestamp == timedelta(seconds=6865)
        assert p4.end_timestamp == timedelta(seconds=7832)
        # Shootout from 7832s to MATCH_END at 8195s.
        assert p5.start_timestamp == timedelta(seconds=7832)
        assert p5.end_timestamp == timedelta(seconds=8195)

    def test_et_halves_have_events(self, et_dataset):
        """Both extra-time halves must receive events.

        Prior to this change, ET events were routed into Period 2 because
        no P3/P4 existed.
        """
        p3_events = [e for e in et_dataset.events if e.period.id == 3]
        p4_events = [e for e in et_dataset.events if e.period.id == 4]
        assert len(p3_events) > 0
        assert len(p4_events) > 0

    def test_shootout_events_present(self, et_dataset):
        """SmrtStats does emit events during the shootout (contrary to
        the downstream DB's 'P5 has no events' claim). Kloppy lands them
        in P5."""
        p5_events = [e for e in et_dataset.events if e.period.id == 5]
        assert len(p5_events) > 0

    def test_exclude_penalty_shootouts(self, et_dataset, et_dataset_excluded):
        """exclude_penalty_shootouts strips only P5, leaving P1-P4 intact."""
        period_ids = [p.id for p in et_dataset_excluded.metadata.periods]
        assert period_ids == [1, 2, 3, 4]
        assert all(e.period.id != 5 for e in et_dataset_excluded.events)
        # The only delta should be P5 events.
        p5_count = sum(1 for e in et_dataset.events if e.period.id == 5)
        assert (
            len(et_dataset.events) - len(et_dataset_excluded.events)
            == p5_count
        )

    def test_et_events_use_extra_time_frame(self, et_dataset):
        """ET events must take ``relative_coord_*`` from
        first_extra_time_markers (resp. second_extra_time_markers), not
        from second_half_markers.

        Teams switch ends between the 2nd half and ET1 (and again between
        ET1 and ET2), so each list encodes the same event in a different
        attacking-direction frame. Pulling coordinates from the
        period-specific bucket keeps downstream spatial analytics
        oriented correctly.

        Anchor: event 239138018 is an ET1 pass at second=5959. Its ET1
        frame encodes relative_coord_x=52.19 while the 2nd-half frame
        encodes 52.81 (mirrored around x=52.5).
        """
        event = et_dataset.get_event_by_id("239138018")
        assert event is not None
        assert event.period.id == 3
        # Kloppy's Point.x matches the raw relative_coord_x straight
        # through (the SmrtStats coord system uses this directly before
        # the coordinate_system transform).
        assert event.raw_event["relative_coord_x"] == pytest.approx(52.19)

    def test_open_play_shots_land_in_attacking_half(self, et_dataset):
        """Open-play shots must have x on the attacking half (x > 52.5).

        Under ACTION_EXECUTING_TEAM orientation the shooting team always
        attacks toward x=105, so any shot with x ≤ 52.5 means the event
        was pulled from the wrong attacking-direction frame — exactly
        the bug that ET1 events exhibit when read from
        second_half_markers instead of first_extra_time_markers.

        Penalty-shootout kicks (P5) are excluded here: SmrtStats encodes
        shootout shots alternately at each team's own attacking-penalty
        spot (x≈92.92 or x≈12.08), so the ``x > 52.5`` invariant does
        not apply to that period.
        """
        open_play_shots = [
            e
            for e in et_dataset.events
            if e.event_type == EventType.SHOT and e.period.id != 5
        ]
        assert len(open_play_shots) > 0
        for shot in open_play_shots:
            assert shot.coordinates.x > 52.5, (
                f"shot {shot.event_id} in P{shot.period.id} has x="
                f"{shot.coordinates.x} (≤ midfield) — suggests a "
                f"coordinate-frame mismatch"
            )

    def test_et1_shots_use_fet_frame(self, et_dataset):
        """Regression anchor: three specific ET1 shots have very
        different coordinates in the two frames. The sh copy places
        them on the defending half; the fet copy places them correctly
        on the attacking side.
        """
        # (event_id, expected x when reading the fet frame, x when
        # the sh-frame copy would have been used).
        cases = [
            ("239138062", 84.53, 20.47),  # SHOT_ON_TARGET
            ("239138089", 90.09, 14.91),  # SHOT_WIDE
            ("239138196", 95.55, 9.45),  # BLOCKED_SHOT
        ]
        for event_id, expected_fet_x, sh_frame_x in cases:
            event = et_dataset.get_event_by_id(event_id)
            assert event is not None, f"event {event_id} missing"
            assert event.period.id == 3
            assert event.coordinates.x == pytest.approx(expected_fet_x), (
                f"ET1 shot {event_id} has x={event.coordinates.x} "
                f"(expected {expected_fet_x} from ET1 frame; "
                f"{sh_frame_x} would indicate a 2nd-half-frame leak)"
            )

    def test_shootout_shots_at_penalty_spots(self, et_dataset):
        """Every shootout (P5) shot lands on a penalty spot.

        SmrtStats encodes each kick from the kicking team's own
        attacking-direction perspective, so kicks alternate between two
        penalty-spot x-coordinates (x ≈ 92.92 and x ≈ 12.08, which are
        ~11 m from each goal line on a 105 m pitch). Every shootout shot
        sits on the pitch-width centerline (y = 34).
        """
        shootout_shots = [
            e
            for e in et_dataset.events
            if e.event_type == EventType.SHOT and e.period.id == 5
        ]
        assert len(shootout_shots) > 0
        for shot in shootout_shots:
            assert shot.coordinates.x in (
                pytest.approx(92.92),
                pytest.approx(12.08),
            ), (
                f"shootout shot {shot.event_id} has unexpected "
                f"x={shot.coordinates.x}"
            )
            assert shot.coordinates.y == pytest.approx(34.0)


# Trimmed real-world feeds, derived from s3://mgp-raw/event/smrtstats/<id>.json
# by keeping every boundary/lineup/formation marker plus the play immediately
# around each boundary and at both ends of each marker list.
#
# ``late_``: HALF_TIME (74) is stamped after the SECOND_HALF (75) marker.
# ``aligned_``: the two share a ``second``, which is the common layout.
#
# Columns: (fixture stem, SECOND_HALF second, HALF_TIME second, P2 end).
# P2 normally ends at MATCH_END; 723447 stamps MATCH_END at 5742 with
# events out to 6044, so there the last event is the end.
LATE_HALF_TIME_FIXTURES = [
    # Nothing at all between the restart and its HALF_TIME.
    ("smrtstats_late_half_time_683623", 2760.0, 2761.0, 5785.0),
    ("smrtstats_late_half_time_687100", 2866.0, 2873.0, 5921.0),
    ("smrtstats_late_half_time_686513", 2837.0, 2838.0, 5899.0),
    # The second-half lineup dump lands inside the gap (12 position
    # markers at 2761), so "no markers in between" does not hold.
    ("smrtstats_late_half_time_683634", 2760.0, 2762.0, 5768.0),
    # Real open play lands inside the gap (passes, a clearance and an
    # aerial duel between 2767 and 2778), and the file carries two
    # HALF_TIME markers: one on the restart, one 11s after it.
    ("smrtstats_late_half_time_723447", 2767.0, 2778.0, 6044.0),
]

ALIGNED_HALF_TIME_FIXTURES = [
    ("smrtstats_aligned_half_time_733180", 2866.0, 2866.0, 5834.0),
    ("smrtstats_aligned_half_time_733179", 2953.0, 2953.0, 5895.0),
]


class TestSmrtStatsHalfTimeMarkerOrdering:
    """Regression tests for a second half lost to a late HALF_TIME marker.

    Affected matches stored a first half of ~2800s with well over a
    thousand events and a second half of 1-7s with none, because the sole
    HALF_TIME marker in the file was timestamped just after the
    SECOND_HALF marker it belongs before. The raw feeds are complete; only
    the period derivation was wrong.

    * 683623 Lens vs Nantes (Ligue 1, 2026-05-08), HALF_TIME +1s
    * 687100 Cesena vs Padova (Serie B, 2026-05-08), HALF_TIME +7s
    * 686513 Cardiff vs Bolton (2026-04-11), HALF_TIME +1s

    733180 (Angers vs Lille) and 733179 (Le Havre vs Monaco) are healthy
    controls: they must be read exactly as before.
    """

    @staticmethod
    def _load(base_dir, stem, **kwargs):
        return smrtstats.load(
            raw_data=base_dir / "files" / f"{stem}.json",
            coordinates="smrtstats",
            **kwargs,
        )

    @pytest.mark.parametrize(
        "stem,second_half,half_time,p2_end",
        LATE_HALF_TIME_FIXTURES + ALIGNED_HALF_TIME_FIXTURES,
    )
    def test_two_regulation_periods_only(
        self, base_dir, stem, second_half, half_time, p2_end
    ):
        """No phantom extra-time or shootout period is invented."""
        dataset = self._load(base_dir, stem)
        assert [p.id for p in dataset.metadata.periods] == [1, 2]

    @pytest.mark.parametrize(
        "stem,second_half,half_time,p2_end",
        LATE_HALF_TIME_FIXTURES + ALIGNED_HALF_TIME_FIXTURES,
    )
    def test_second_half_spans_the_restart_to_match_end(
        self, base_dir, stem, second_half, half_time, p2_end
    ):
        """P2 runs from the SECOND_HALF marker to MATCH_END.

        The late HALF_TIME is the first half's, so it never shortens P2 —
        not to ``half_time``, and not to anything else short of the whistle.
        """
        p1, p2 = self._load(base_dir, stem).metadata.periods
        assert p1.start_timestamp <= timedelta(seconds=1)
        assert p1.end_timestamp == timedelta(seconds=second_half)
        assert p2.start_timestamp == timedelta(seconds=second_half)
        assert p2.end_timestamp == timedelta(seconds=p2_end)

    @pytest.mark.parametrize(
        "stem,second_half,half_time,p2_end",
        LATE_HALF_TIME_FIXTURES + ALIGNED_HALF_TIME_FIXTURES,
    )
    def test_both_halves_are_a_plausible_length(
        self, base_dir, stem, second_half, half_time, p2_end
    ):
        """Every regulation half lasts at least 40 minutes.

        The bug's signature was a 1-7 second second half, so this is the
        assertion that fails loudest if the boundary logic regresses.
        """
        for period in self._load(base_dir, stem).metadata.periods:
            duration = period.end_timestamp - period.start_timestamp
            assert duration > timedelta(
                minutes=40
            ), f"{stem} period {period.id} lasts {duration}"

    @pytest.mark.parametrize(
        "stem,second_half,half_time,p2_end",
        LATE_HALF_TIME_FIXTURES + ALIGNED_HALF_TIME_FIXTURES,
    )
    def test_both_halves_receive_events(
        self, base_dir, stem, second_half, half_time, p2_end
    ):
        dataset = self._load(base_dir, stem)
        for period_id in (1, 2):
            assert any(
                e.period.id == period_id for e in dataset.events
            ), f"{stem} period {period_id} has no events"

    @pytest.mark.parametrize(
        "stem,second_half,half_time,p2_end",
        LATE_HALF_TIME_FIXTURES + ALIGNED_HALF_TIME_FIXTURES,
    )
    def test_excluding_shootouts_drops_nothing(
        self, base_dir, stem, second_half, half_time, p2_end
    ):
        """These matches have no shootout, so the flag is a no-op.

        This is the assertion closest to the reported symptom: every MGP
        ingest passes ``exclude_penalty_shootouts=True``, and it was that
        flag which turned a mislabelled second half into a missing one.
        """
        full = self._load(base_dir, stem)
        excluded = self._load(base_dir, stem, exclude_penalty_shootouts=True)
        assert [p.id for p in excluded.metadata.periods] == [
            p.id for p in full.metadata.periods
        ]
        assert len(excluded.events) == len(full.events)

    @pytest.mark.parametrize(
        "stem,second_half,half_time,p2_end", LATE_HALF_TIME_FIXTURES
    )
    def test_fixture_really_has_a_late_half_time(
        self, base_dir, stem, second_half, half_time, p2_end
    ):
        """Guard the fixtures themselves.

        Trimming must not have dropped the marker that makes these files
        interesting, or the tests above would pass vacuously.
        """
        raw = json.loads((base_dir / "files" / f"{stem}.json").read_text())
        markers = (raw["first_half_markers"] or []) + (
            raw["second_half_markers"] or []
        )
        assert half_time > second_half
        assert half_time in [
            e["second"] for e in markers if e["action_id"] == 74
        ]
        assert [e["second"] for e in markers if e["action_id"] == 75] == [
            second_half
        ]
