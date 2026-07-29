import json
from collections import defaultdict
from datetime import timedelta
from io import BytesIO
from typing import cast

import pytest

from kloppy import korastats
from kloppy.domain import (
    BallState,
    BodyPart,
    BodyPartQualifier,
    CarryResult,
    DuelQualifier,
    DuelResult,
    DuelType,
    EventDataset,
    FormationType,
    InterceptionResult,
    Orientation,
    PassResult,
    Point,
    Point3D,
    Provider,
    SetPieceQualifier,
    SetPieceType,
    ShotResult,
    SubstitutionEvent,
    Time,
)
from kloppy.domain.models import PositionType
from kloppy.infra.serializers.event.korastats.deserializer import (
    parse_formation,
    parse_starting_formations,
)
from kloppy.domain.models.event import (
    EventType,
    GoalkeeperActionType,
    GoalkeeperQualifier,
    PassQualifier,
    PassType,
)


@pytest.fixture(scope="module")
def dataset(base_dir) -> EventDataset:
    dataset = korastats.load(
        event_data=base_dir / "files" / "korastats_events.json",
        squads_data=base_dir / "files" / "korastats_squads.json",
        home_formation_data=base_dir
        / "files"
        / "korastats_formation_home.json",
        away_formation_data=base_dir
        / "files"
        / "korastats_formation_away.json",
        coordinates="korastats",
    )

    return dataset


class TestKoraStatsMetadata:
    """Tests related to deserializing metadata"""

    def test_provider(self, dataset):
        """It should set the KoraStats provider"""
        assert dataset.metadata.provider == Provider.KORASTATS

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
        assert dataset.metadata.teams[0].team_id == "10107"
        assert dataset.metadata.teams[0].starting_formation == FormationType(
            "4-3-3"
        )
        assert dataset.metadata.teams[1].team_id == "23109"
        assert dataset.metadata.teams[1].starting_formation == FormationType(
            "4-3-3"
        )

        # The teams should have the correct players
        player = dataset.metadata.teams[0].get_player_by_id("194622")
        assert player.player_id == "194622"
        assert player.jersey_no == 1
        assert str(player) == "Samuel Erik Oskar Brolin"

    def test_player_position(self, dataset):
        """It should set the correct player position from the events"""
        player = dataset.metadata.teams[0].get_player_by_id("194622")

        assert player.starting_position == PositionType.Goalkeeper
        assert player.starting

        # Substituted players have a position
        sub_player = dataset.metadata.teams[0].get_player_by_id("436613")
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
        assert home_starting_gk.player_id == "194622"
        assert home_starting_gk.jersey_no == 1

        home_starting_rcb = dataset.metadata.teams[0].get_player_by_position(
            PositionType.CenterMidfield,
            time=Time(period=period_1, timestamp=timedelta(seconds=0)),
        )
        assert home_starting_rcb.player_id == "195863"

        home_ending_rcb = dataset.metadata.teams[0].get_player_by_position(
            PositionType.CenterMidfield,
            time=Time(period=period_2, timestamp=timedelta(seconds=45 * 60)),
        )
        assert home_ending_rcb.player_id == "436613"

        away_starting_gk = dataset.metadata.teams[1].get_player_by_position(
            PositionType.Goalkeeper,
            time=Time(period=period_1, timestamp=timedelta(seconds=92)),
        )
        assert away_starting_gk.player_id == "436614"

    def test_periods(self, dataset):
        """It should create the periods"""
        assert len(dataset.metadata.periods) == 2
        assert dataset.metadata.periods[0].id == 1


class TestKoraStatsEvent:
    """Generic tests related to deserializing events"""

    def test_unique_event_ids(self, dataset: EventDataset):
        """It should create unique event ids"""
        event_ids = defaultdict(int)
        for event in dataset.events:
            event_ids[event.event_id] += 1
        assert all(
            v == 1 for v in event_ids.values()
        ), "Event IDs are not unique"

    def test_generic_attributes(self, dataset: EventDataset):
        """Test generic event attributes"""
        event = dataset.get_event_by_id("144880351")
        assert event.event_id == "144880351"
        assert event.team.team_id == "10107"
        assert event.ball_owning_team.team_id == "10107"
        assert event.player.full_name == "Gibril Sosseh"
        assert event.coordinates == Point(x=50, y=50)
        assert event.raw_event["_id"] == 144880351
        assert event.period.id == 1
        assert event.timestamp == timedelta(microseconds=467000)
        # assert event.ball_state == BallState.ALIVE

    def test_timestamp(self, dataset):
        """It should set the correct timestamp, reset to zero after each period"""
        kick_offs = [
            e
            for e in dataset.events
            if e.event_type == EventType.PASS
            and e.get_qualifier_value(SetPieceQualifier)
            == SetPieceType.KICK_OFF
        ]
        kickoff_p1 = kick_offs[0]
        assert kickoff_p1.timestamp == timedelta(microseconds=467000)
        kick_off_p2 = kick_offs[1]
        assert kick_off_p2.timestamp == timedelta(microseconds=427000)


class TestKoraStatsPassEvent:
    """Tests related to deserialzing pass events"""

    def test_deserialize_all(self, dataset: EventDataset):
        """It should deserialize all pass events"""
        events = dataset.find_all("pass")
        assert len(events) == 869

    def test_open_play(self, dataset: EventDataset):
        """Verify specific attributes of simple open play pass"""
        pass_event = dataset.get_event_by_id("144880455")
        # A pass should have a result
        assert pass_event.result == PassResult.COMPLETE
        # A pass should have end coordinates
        assert pass_event.coordinates == Point(x=20, y=62)
        assert pass_event.receiver_coordinates == Point(x=8, y=59)
        # A pass should have an end timestamp
        assert pass_event.timestamp == timedelta(
            seconds=21, microseconds=181000
        )
        assert pass_event.receive_timestamp == timedelta(
            seconds=25, microseconds=85000
        )
        # A pass should have a receiver
        assert pass_event.receiver_player.player_id == "436614"
        # A pass can have set piece qualifiers
        assert pass_event.get_qualifier_value(SetPieceQualifier) is None
        # A pass can have pass qualifiers
        assert pass_event.get_qualifier_value(PassQualifier) is None

    def test_set_pieces(self, dataset: EventDataset):
        """It should add set piece qualifiers to free kick passes"""
        assert (
            len(
                [
                    e
                    for e in dataset.events
                    if e.get_qualifier_value(SetPieceQualifier)
                    == SetPieceType.FREE_KICK
                ]
            )
            == 22
        )

    def test_assists(self, dataset: EventDataset):
        shot_assists = [
            e
            for e in dataset.events
            if PassType.SHOT_ASSIST in e.get_qualifier_values(PassQualifier)
        ]
        assert len(shot_assists) == 16

        goal_assists = [
            e
            for e in dataset.events
            if PassType.ASSIST in e.get_qualifier_values(PassQualifier)
        ]
        assert len(goal_assists) == 1

    def test_pass_result_counts(self, dataset: EventDataset):
        """It should have the correct number of passes for each result type."""
        passes = dataset.find_all("pass")

        out_passes = [p for p in passes if p.result == PassResult.OUT]
        incomplete_passes = [
            p for p in passes if p.result == PassResult.INCOMPLETE
        ]
        complete_passes = [
            p for p in passes if p.result == PassResult.COMPLETE
        ]

        assert len(out_passes) == 15
        assert len(incomplete_passes) == 181
        assert len(complete_passes) == 673


class TestKoraStatsInterceptionEvent:
    """Tests related to deserialzing pass events"""

    def test_deserialize_all(self, dataset: EventDataset):
        """It should deserialize all shot events"""
        events = dataset.find_all("interception")
        assert len(events) == 100

    def test_interception(self, dataset: EventDataset):
        """It should split interception passes into two events"""
        interception = dataset.get_event_by_id("144880413")
        assert interception.event_type == EventType.INTERCEPTION
        assert interception.result == InterceptionResult.SUCCESS


class TestKoraStatsShotEvent:
    """Tests related to deserialzing 16/Shot events"""

    def test_deserialize_all(self, dataset: EventDataset):
        """It should deserialize all shot events"""
        events = dataset.find_all("shot")
        assert len(events) == 21

    def test_open_play(self, dataset: EventDataset):
        """Verify specific attributes of simple open play shot"""
        shot = dataset.get_event_by_id("144881556")
        # A shot event should have a result
        assert shot.result == ShotResult.GOAL
        # A shot event should have end coordinates
        assert shot.result_coordinates == Point3D(
            x=100, y=45.86666666666667, z=37
        )
        # A shot event should have a body part
        assert (
            shot.get_qualifier_value(BodyPartQualifier) == BodyPart.RIGHT_FOOT
        )
        # An open play shot should not have a set piece qualifier
        assert shot.get_qualifier_value(SetPieceQualifier) is None

    def test_one_on_one_goal(self, dataset: EventDataset):
        """OneOnOne events should be deserialized as shots"""
        shot = dataset.get_event_by_id("144880629")
        assert shot.event_type == EventType.SHOT
        assert shot.result == ShotResult.GOAL
        assert shot.coordinates == Point(x=95, y=44)
        assert shot.result_coordinates == Point3D(
            x=100, y=45.86666666666667, z=27
        )
        assert (
            shot.get_qualifier_value(BodyPartQualifier) == BodyPart.RIGHT_FOOT
        )


class TestKoraStatsOwnGoalEvent:
    """Tests related to deserializing own goal events.

    KoraStats emits own goals as a pair:
    - ATTACK_OWN_GOAL_IN_OPPONENT (5, 30) on the benefiting team's side
      (no player_id)
    - GOALKEEPER_OWN_GOAL_CONCEDED (2, 49) on the conceding team's side,
      attached to the goalkeeper.

    Only the conceding-side event should produce a SHOT with
    ShotResult.OWN_GOAL.
    """

    def test_own_goal_count(self, dataset: EventDataset):
        """Exactly one own-goal shot event per own goal should be emitted."""
        shots = dataset.find_all("shot")
        own_goals = [s for s in shots if s.result == ShotResult.OWN_GOAL]
        assert len(own_goals) == 1

    def test_own_goal_attribution(self, dataset: EventDataset):
        """Own-goal shot should be attributed to the conceding team."""
        # _id 144883828 is the GOALKEEPER_OWN_GOAL_CONCEDED event
        # conceded by Kalmar FF (team_id 10107).
        shot = dataset.get_event_by_id("144883828")
        assert shot is not None
        assert shot.event_type == EventType.SHOT
        assert shot.result == ShotResult.OWN_GOAL
        assert shot.team.team_id == "10107"

    def test_benefiting_side_dropped(self, dataset: EventDataset):
        """The benefiting-side event should not produce a separate shot."""
        # _id 144883827 is the ATTACK_OWN_GOAL_IN_OPPONENT event
        # which should be silently dropped.
        assert dataset.get_event_by_id("144883827") is None


class TestKoraStatsClearanceEvent:
    """Tests related to deserializing 9/Clearance events"""

    def test_deserialize_all(self, dataset: EventDataset):
        """It should deserialize all clearance events"""
        events = dataset.find_all("clearance")
        assert len(events) == 10

    # def test_attributes(self, dataset: EventDataset):
    #     """Verify specific attributes of clearances"""
    #     clearance = dataset.get_event_by_id("42")
    #     # A clearance has no result
    #     assert clearance.result is None
    #     assert (
    #             clearance.get_qualifier_value(BodyPartQualifier)
    #             == BodyPart.RIGHT_FOOT
    #     )


class TestKoraStatsDuelEvent:
    """Tests related to deserializing 1/Duel events"""

    def test_deserialize_all(self, dataset: EventDataset):
        """It should deserialize all duel and 50/50 events"""
        events = dataset.find_all("duel")
        assert len(events) == 100

    # def test_attributes(self, dataset: EventDataset):
    #     """Verify specific attributes of duels"""
    #     duel = dataset.get_event_by_id("45")
    #     # A duel should have a result
    #     assert duel.result == DuelResult.WON
    #     # A duel should have a duel type
    #     assert duel.get_qualifier_values(DuelQualifier) == [DuelType.GROUND]
    #     # A duel does not have a body part
    #     assert duel.get_qualifier_value(BodyPartQualifier) == BodyPart.OTHER
    #
    #     # it should create an artificial duel lost event for the opponent
    #     lost_duel = dataset.get_event_by_id("37-ground-duel-45")
    #     # A duel should have a result
    #     assert lost_duel.result == DuelResult.LOST
    #     # A duel should have a duel type
    #     assert lost_duel.get_qualifier_values(DuelQualifier) == [
    #         DuelType.GROUND
    #     ]
    #     # A duel does not have a body part
    #     assert duel.get_qualifier_value(BodyPartQualifier) == BodyPart.OTHER

    # def test_aerial_duel(self, dataset: EventDataset):
    #     duel = dataset.get_event_by_id("15-aerial-duel-135")
    #     assert duel.get_qualifier_values(DuelQualifier) == [
    #         DuelType.LOOSE_BALL,
    #         DuelType.AERIAL,
    #     ]


class TestKoraStatsTackleEvent:
    """Tests for KoraStats Tackle (event_id=33) and TackleClear (event_id=36).

    event_id=33 is defender-attributed: the player_id on the row is the
    defender on the defending team. result_id=10 means the defender won
    the duel (kept the ball away), result_id=11 means the defender lost
    (got dribbled past). event_id=36 (DEFENSIVE_TACKLE_CLEAR) is always
    a defender-won duel.

    See TAS-2898.
    """

    def test_tackle_success_is_defending_duel_won(self, dataset: EventDataset):
        # _id=144880593, event_id=33, result_id=10 → defender won
        event = dataset.get_event_by_id("144880593")
        assert event.event_type == EventType.DUEL
        assert event.result == DuelResult.WON
        assert DuelType.TACKLE in event.get_qualifier_values(DuelQualifier)
        # player_id on the row is the defender
        assert event.player.player_id == "358812"
        # ball is owned by the opposing team (the attacker who was tackled)
        assert event.ball_owning_team is not None
        assert event.ball_owning_team != event.team
        assert event.ball_owning_team.team_id == "23109"

    def test_tackle_fail_is_defending_duel_lost(self, dataset: EventDataset):
        # _id=144880354, event_id=33, result_id=11 → defender lost
        event = dataset.get_event_by_id("144880354")
        assert event.event_type == EventType.DUEL
        assert event.result == DuelResult.LOST
        assert DuelType.TACKLE in event.get_qualifier_values(DuelQualifier)
        assert event.player.player_id == "436626"
        assert event.ball_owning_team is not None
        assert event.ball_owning_team != event.team
        assert event.ball_owning_team.team_id == "10107"

    def test_tackle_clear_is_defending_duel_won(self, dataset: EventDataset):
        # _id=144880577, event_id=36 → defender won (always)
        event = dataset.get_event_by_id("144880577")
        assert event.event_type == EventType.DUEL
        assert event.result == DuelResult.WON
        assert DuelType.TACKLE in event.get_qualifier_values(DuelQualifier)
        assert event.ball_owning_team is not None
        assert event.ball_owning_team != event.team

    def test_tackle_results_have_correct_distribution(
        self, dataset: EventDataset
    ):
        """Every tackle-class duel should have a typed DuelResult.

        Fixture contains: event_id=33 → 20 success + 21 fail;
        event_id=36 → 25 (always won). So the tackle duels should be
        45 WON and 21 LOST, with no None results.
        """
        duels = dataset.find_all("duel")
        tackle_duels = [
            d
            for d in duels
            if DuelType.TACKLE in (d.get_qualifier_values(DuelQualifier) or [])
        ]
        won = sum(1 for d in tackle_duels if d.result == DuelResult.WON)
        lost = sum(1 for d in tackle_duels if d.result == DuelResult.LOST)
        assert won == 45
        assert lost == 21
        assert won + lost == len(tackle_duels)


class TestsKoraStatsCardEvent:
    def test_deserialize_all(self, dataset: EventDataset):
        """It should create a card event for each card given"""
        events = dataset.find_all("card")
        assert len(events) == 8
        for event in events:
            assert event.event_type == EventType.CARD


class TestKoraStatsGoalkeeperEvent:
    """Tests related to deserializing 30/Goalkeeper events"""

    def test_deserialize_all(self, dataset: EventDataset):
        """It should deserialize all goalkeeper events"""
        events = dataset.find_all("goalkeeper")
        assert len(events) == 15

    # def test_save(self, dataset: EventDataset):
    #     """It should deserialize goalkeeper saves"""
    #     # A save should be deserialized as a goalkeeper event
    #     save = dataset.get_event_by_id("1137")
    #     assert save.get_qualifier_value(GoalkeeperQualifier) == (
    #         GoalkeeperActionType.SAVE
    #     )
    #
    # def test_catch(self, dataset: EventDataset):
    #     """It should deserialize goalkeeper catch"""
    #     collected = dataset.get_event_by_id("187")
    #     assert collected.get_qualifier_value(GoalkeeperQualifier) == (
    #         GoalkeeperActionType.CLAIM
    #     )


class TestKoraStatsSubstitutionEvent:
    """Tests related to deserializing 18/Substitution events"""

    def test_deserialize_all(self, dataset: EventDataset):
        """It should deserialize all substitution events"""
        events = dataset.find_all("substitution")
        assert len(events) == 8

        # Verify that the player and replacement player are set correctly
        # subs = [
        #     ("15", "1"),
        #     ("4", "6"),
        #     ("31", "29"),
        #     ("38", "32"),
        #     ("37", "28"),
        #     ("7", "12"),
        # ]
        # for event_idx, (player_id, replacement_player_id) in enumerate(subs):
        #     event = cast(SubstitutionEvent, events[event_idx])
        #     assert event.player == event.team.get_player_by_id(player_id)
        #     assert event.replacement_player == event.team.get_player_by_id(
        #         replacement_player_id
        #     )

    def test_pair_bracketed_substitutions(self):
        """It should pair out/in even when the pairs are not adjacent.

        KoraStats brackets substitution pairs when both teams sub at the same
        stoppage: two SubstituteOut events emit before their SubstituteIn
        events, so an out/in pair is no longer adjacent.
        """
        from kloppy.infra.serializers.event.korastats.deserializer import (
            KoraStatsDeserializer,
        )

        # team 1's out (idx 0) brackets team 2's adjacent pair; its matching
        # in is at idx 3.
        raw_events = [
            {
                "extra": "SubstituteOut",
                "team_id": 1,
                "half": 2,
                "player_id": 10,
            },
            {
                "extra": "SubstituteOut",
                "team_id": 2,
                "half": 2,
                "player_id": 20,
            },
            {
                "extra": "SubstituteIn",
                "team_id": 2,
                "half": 2,
                "player_id": 21,
            },
            {
                "extra": "SubstituteIn",
                "team_id": 1,
                "half": 2,
                "player_id": 11,
            },
        ]
        KoraStatsDeserializer.pair_substitutions(raw_events)

        assert raw_events[0]["_replacement_player_id"] == 11
        assert raw_events[1]["_replacement_player_id"] == 21


class TestKoraStatsFoulCommittedEvent:
    """Tests related to deserializing 2/Foul Committed events"""

    def test_deserialize_all(self, dataset: EventDataset):
        """It should deserialize all foul committed events"""
        events = dataset.find_all("foul_committed")
        assert len(events) == 36


class TestKoraStatsRecoveryEvent:
    """Tests related to deserializing 23/Recovery events"""

    def test_deserialize_recoveries(self, dataset: EventDataset):
        events = dataset.find_all("recovery")
        assert len(events) == 157


class TestKoraStatsFormation:
    """Tests related to deserializing the MatchFormation feeds"""

    @pytest.mark.parametrize(
        "raw_formation,expected",
        [
            ("1-433", FormationType("4-3-3")),
            ("1-442", FormationType("4-4-2")),
            ("1-4240", FormationType("4-2-4-0")),
            ("1-523", FormationType("5-2-3")),
            ("1-541", FormationType("5-4-1")),
            # Partial strings: fewer or more than ten outfield players
            ("1-53", FormationType.UNKNOWN),
            ("1-5301", FormationType.UNKNOWN),
            ("1-4331", FormationType.UNKNOWN),
            # A second goalkeeper is not a formation
            ("2-423", FormationType.UNKNOWN),
            # Missing values
            (" - ", FormationType.UNKNOWN),
            ("", FormationType.UNKNOWN),
            (None, FormationType.UNKNOWN),
        ],
    )
    def test_parse_formation(self, raw_formation, expected):
        """It should read the goalkeeper-first formation strings"""
        assert parse_formation(raw_formation) == expected

    def test_keys_formations_by_team_id(self):
        """It should key each feed by its own team id, not by argument order"""
        home_feed = BytesIO(
            json.dumps(
                {"teamId": 10107, "startingLineupFormation": "1-433"}
            ).encode()
        )
        away_feed = BytesIO(
            json.dumps(
                {"teamId": 23109, "startingLineupFormation": "1-532"}
            ).encode()
        )

        # Pass the away feed first to prove the order does not matter
        assert parse_starting_formations([away_feed, home_feed]) == {
            "10107": FormationType("4-3-3"),
            "23109": FormationType("5-3-2"),
        }

    def test_without_formation_data(self, base_dir):
        """It should fall back to an unknown formation when the feeds are absent"""
        dataset = korastats.load(
            event_data=base_dir / "files" / "korastats_events.json",
            squads_data=base_dir / "files" / "korastats_squads.json",
            coordinates="korastats",
        )

        assert (
            dataset.metadata.teams[0].starting_formation
            == FormationType.UNKNOWN
        )
        assert (
            dataset.metadata.teams[1].starting_formation
            == FormationType.UNKNOWN
        )


def test_add_synthetic_event(dataset: EventDataset):
    events_dataset = (
        dataset.add_synthetic_event(EventType.CARRY)
        .add_synthetic_event(EventType.BALL_RECEIPT)
        .add_state(["score", "sequence"])
    )
    pass
