from datetime import timedelta

from kloppy.domain import (
    EventType,
    Unit,
)
from kloppy.utils import performance_logging
from kloppy import statsbomb, statsperform


class TestSyntheticEventGenerator:
    """"""

    def _load_dataset_statsperform(
        self, base_dir, base_filename="statsperform"
    ):
        return statsperform.load_event(
            ma1_data=base_dir / f"files/{base_filename}_event_ma1.json",
            ma3_data=base_dir / f"files/{base_filename}_event_ma3.json",
        )

    def _load_dataset_statsbomb(
        self, base_dir, base_filename="statsbomb", event_types=None
    ):
        return statsbomb.load(
            event_data=base_dir / f"files/{base_filename}_event.json",
            lineup_data=base_dir / f"files/{base_filename}_lineup.json",
            event_types=event_types,
        )

    def calculate_carry_accuracy(
        self, real_carries, generated_carries, real_carries_with_min_length
    ):
        def is_match(real_carry, generated_carry):
            return (
                real_carry.player
                and generated_carry.player
                and real_carry.player.player_id
                == generated_carry.player.player_id
                and real_carry.period == generated_carry.period
                and abs(real_carry.timestamp - generated_carry.timestamp)
                < timedelta(seconds=5)
            )

        true_positives = 0
        matched_real_carries = set()
        for generated_carry in generated_carries:
            for idx, real_carry in enumerate(real_carries):
                if idx in matched_real_carries:
                    continue
                if is_match(real_carry, generated_carry):
                    true_positives += 1
                    matched_real_carries.add(idx)
                    break

        false_negatives = 0
        matched_generated_carries = set()
        for real_carry in real_carries_with_min_length:
            found_match = False
            for idx, generated_carry in enumerate(generated_carries):
                if idx in matched_generated_carries:
                    continue
                if is_match(real_carry, generated_carry):
                    found_match = True
                    matched_generated_carries.add(idx)
                    break
            if not found_match:
                false_negatives += 1

        false_positives = len(generated_carries) - true_positives

        accuracy = true_positives / (
            true_positives + false_positives + false_negatives
        )

        print("TP:", true_positives)
        print("FP:", false_positives)
        print("FN:", false_negatives)
        print("accuracy:", accuracy)

        return accuracy

    def test_synthetic_carry_generator(self, base_dir):
        dataset_with_carries = self._load_dataset_statsbomb(base_dir)
        pitch = dataset_with_carries.metadata.pitch_dimensions

        min_length_meters = 3
        max_length_meters = 60
        max_duration = timedelta(seconds=10)

        all_statsbomb_caries = dataset_with_carries.find_all("carry")
        all_qualifying_statsbomb_queries = [
            carry
            for carry in all_statsbomb_caries
            if (
                min_length_meters
                <= pitch.distance_between(
                    carry.coordinates, carry.end_coordinates, Unit.METERS
                )
                <= max_length_meters
                and carry.end_timestamp - carry.timestamp < max_duration
            )
        ]

        dataset = self._load_dataset_statsbomb(
            base_dir,
            event_types=[
                event.value for event in EventType if event.value != "CARRY"
            ],
        )

        with performance_logging("generating synthetic events"):
            dataset = dataset.add_synthetic_event(
                EventType.CARRY,
                min_length_meters=min_length_meters,
                max_length_meters=max_length_meters,
                max_duration=max_duration,
            )
        all_carries = dataset.find_all("carry")
        assert (
            self.calculate_carry_accuracy(
                all_statsbomb_caries,
                all_carries,
                all_qualifying_statsbomb_queries,
            )
            > 0.80
        )

    def test_synthetic_carries_get_a_duration_where_the_feed_allows(
        self, base_dir
    ):
        """A generated carry should span real time wherever that is knowable.

        Opta reports a completed pass's arrival as the timestamp of the next
        on-ball event, so the carry in between would start exactly when it ends
        - zero duration, infinite implied speed. On this fixture that was 251 of
        311 generated carries. Estimating the ball's flight time instead
        recovers a real duration for nearly all of them.
        """
        dataset = self._load_dataset_statsperform(base_dir)
        dataset = dataset.add_synthetic_event(EventType.CARRY)

        carries = dataset.find_all("carry")
        assert carries, "expected the fixture to generate carries"

        degenerate = [
            carry
            for carry in carries
            if carry.end_timestamp - carry.timestamp <= timedelta(0)
        ]
        assert len(degenerate) / len(carries) < 0.10, (
            f"{len(degenerate)} of {len(carries)} carries still have a "
            f"duration of zero or less"
        )

    def test_carries_survive_an_unknowable_duration(self, base_dir):
        """A carry whose duration cannot be established must still be emitted.

        Where the gap to the next action is smaller than the ball's flight
        time, no estimate produces a positive duration. Dropping the carry
        there would hand its distance to the preceding pass, so a shot after
        "received, carried" reads as a through ball finished first time - the
        error this generator caused on Opta goals before it was fixed.

        So the remaining zero-duration carries must be present, not absent.
        """
        dataset = self._load_dataset_statsperform(base_dir)
        dataset = dataset.add_synthetic_event(EventType.CARRY)

        carries = dataset.find_all("carry")
        degenerate = [
            carry
            for carry in carries
            if carry.end_timestamp - carry.timestamp <= timedelta(0)
        ]
        assert degenerate, (
            "this fixture is expected to contain carries the feed gives no "
            "usable interval for; none were emitted, so they are being dropped"
        )
        # and they carry a real displacement - that is why they are kept
        for carry in degenerate:
            assert carry.coordinates != carry.end_coordinates

    def test_synthetic_ball_receipt_generator(self, base_dir):

        dataset = self._load_dataset_statsbomb(
            base_dir,
        )

        with performance_logging("generating synthetic events"):
            dataset = dataset.add_synthetic_event(
                EventType.BALL_RECEIPT,
            )
        all_receivals = dataset.find_all("ball_receipt")


class TestOwnGoalForDomain:
    """Domain-level tests for the new GoalQualifier and OwnGoalForEvent."""

    def test_goal_qualifier_is_bool_qualifier(self):
        from kloppy.domain import GoalQualifier
        from kloppy.domain.models.event import BoolQualifier

        q = GoalQualifier(value=True)
        assert isinstance(q, BoolQualifier)
        assert q.name == "goal"
        assert q.to_dict() == {"is_goal": True}

    def test_own_goal_for_event_type_exists(self):
        from kloppy.domain import EventType

        assert EventType.OWN_GOAL_FOR.value == "OWN_GOAL_FOR"

    def test_own_goal_for_event_class_attributes(self):
        from kloppy.domain import OwnGoalForEvent, EventType

        assert OwnGoalForEvent.event_type == EventType.OWN_GOAL_FOR
        assert OwnGoalForEvent.event_name == "own_goal_for"

    def test_event_factory_build_own_goal_for(self):
        from kloppy.domain import EventFactory, OwnGoalForEvent

        factory = EventFactory()
        event = factory.build_own_goal_for(
            event_id="ogf-1",
            coordinates=None,
            team=None,
            player=None,
            ball_owning_team=None,
            ball_state=None,
            period=None,
            timestamp=None,
            raw_event=None,
            qualifiers=None,
            related_event_ids=[],
            result=None,
        )
        assert isinstance(event, OwnGoalForEvent)
        assert event.event_id == "ogf-1"
        assert event.player is None


class TestGoalQualifierAttachment:
    """Tests for automatic GoalQualifier attachment at EventDataset construction."""

    def _load_dataset_statsbomb(self, base_dir, base_filename="statsbomb"):
        from kloppy import statsbomb
        return statsbomb.load(
            event_data=base_dir / f"files/{base_filename}_event.json",
            lineup_data=base_dir / f"files/{base_filename}_lineup.json",
        )

    def test_goal_qualifier_attached_to_goal_shots(self, base_dir):
        from kloppy.domain import GoalQualifier, ShotEvent, ShotResult

        dataset = self._load_dataset_statsbomb(base_dir)
        goal_shots = [
            e
            for e in dataset.events
            if isinstance(e, ShotEvent) and e.result == ShotResult.GOAL
        ]
        assert len(goal_shots) > 0, (
            "fixture must contain at least one GOAL shot for this test"
        )
        for shot in goal_shots:
            assert shot.qualifiers is not None
            assert any(
                isinstance(q, GoalQualifier) for q in shot.qualifiers
            ), f"GOAL shot {shot.event_id} missing GoalQualifier"

    def test_goal_qualifier_not_attached_to_own_goal_shots(self, base_dir):
        from kloppy.domain import GoalQualifier, ShotEvent, ShotResult

        dataset = self._load_dataset_statsbomb(base_dir)
        own_goal_shots = [
            e
            for e in dataset.events
            if isinstance(e, ShotEvent) and e.result == ShotResult.OWN_GOAL
        ]
        assert len(own_goal_shots) > 0, (
            "fixture must contain at least one OWN_GOAL shot for this test"
        )
        for shot in own_goal_shots:
            qualifiers = shot.qualifiers or []
            assert not any(
                isinstance(q, GoalQualifier) for q in qualifiers
            ), f"OWN_GOAL shot {shot.event_id} should NOT have GoalQualifier"

    def test_goal_qualifier_idempotent(self, base_dir):
        """Running __post_init__ logic twice should not duplicate qualifiers."""
        from kloppy.domain import GoalQualifier, ShotEvent, ShotResult

        dataset = self._load_dataset_statsbomb(base_dir)
        # Force a second pass of the attachment logic.
        dataset._attach_goal_qualifiers()

        goal_shots = [
            e
            for e in dataset.events
            if isinstance(e, ShotEvent) and e.result == ShotResult.GOAL
        ]
        for shot in goal_shots:
            count = sum(
                1 for q in (shot.qualifiers or []) if isinstance(q, GoalQualifier)
            )
            assert count == 1, (
                f"GOAL shot {shot.event_id} has {count} GoalQualifiers, expected 1"
            )


class TestSyntheticOwnGoalForGenerator:
    """Tests for SyntheticOwnGoalForGenerator."""

    def _load_dataset_statsbomb(self, base_dir, base_filename="statsbomb"):
        from kloppy import statsbomb
        return statsbomb.load(
            event_data=base_dir / f"files/{base_filename}_event.json",
            lineup_data=base_dir / f"files/{base_filename}_lineup.json",
        )

    def test_no_own_goals_produces_no_synthetic_events(self, base_dir):
        """Filter out shots; the generator should produce no OwnGoalForEvents."""
        from kloppy.domain import EventType, OwnGoalForEvent
        from kloppy import statsbomb

        # Load only non-shot events to guarantee no OWN_GOAL shots.
        dataset = statsbomb.load(
            event_data=base_dir / "files/statsbomb_event.json",
            lineup_data=base_dir / "files/statsbomb_lineup.json",
            event_types=[
                e.value for e in EventType if e != EventType.SHOT
            ],
        )
        before = len([e for e in dataset.events if isinstance(e, OwnGoalForEvent)])
        dataset = dataset.add_synthetic_event(EventType.OWN_GOAL_FOR)
        after = len([e for e in dataset.events if isinstance(e, OwnGoalForEvent)])
        assert before == 0
        assert after == 0

    def test_one_own_goal_produces_one_synthetic_event(self, base_dir):
        from kloppy.domain import (
            EventType,
            GoalQualifier,
            OwnGoalForEvent,
            ShotEvent,
            ShotResult,
        )

        dataset = self._load_dataset_statsbomb(base_dir)
        own_goal_shots = [
            e
            for e in dataset.events
            if isinstance(e, ShotEvent) and e.result == ShotResult.OWN_GOAL
        ]
        assert len(own_goal_shots) >= 1

        dataset = dataset.add_synthetic_event(EventType.OWN_GOAL_FOR)

        synthetic_events = [
            e for e in dataset.events if isinstance(e, OwnGoalForEvent)
        ]
        assert len(synthetic_events) == len(own_goal_shots)

        # Pick the first own goal and verify the corresponding synthetic event.
        source = own_goal_shots[0]
        synthetic = next(
            e for e in synthetic_events
            if e.event_id == f"own_goal_for-{source.event_id}"
        )

        # Positioned immediately after the source.
        events_list = list(dataset.events)
        source_idx = events_list.index(source)
        assert events_list[source_idx + 1] is synthetic

        # Beneficiary team (opponent of source).
        teams = dataset.metadata.teams
        opponent = next(t for t in teams if t != source.team)
        assert synthetic.team == opponent

        # Player is None.
        assert synthetic.player is None

        # Coordinates copied from source.
        assert synthetic.coordinates == source.coordinates

        # GoalQualifier is present.
        assert synthetic.qualifiers is not None
        assert any(
            isinstance(q, GoalQualifier) for q in synthetic.qualifiers
        )

        # Linked to source via related_event_ids.
        assert synthetic.related_event_ids == [source.event_id]

    def test_generator_is_idempotent(self, base_dir):
        from kloppy.domain import EventType, OwnGoalForEvent

        dataset = self._load_dataset_statsbomb(base_dir)
        dataset = dataset.add_synthetic_event(EventType.OWN_GOAL_FOR)
        first_run_ids = sorted(
            e.event_id for e in dataset.events
            if isinstance(e, OwnGoalForEvent)
        )

        # Second run on the same dataset.
        dataset = dataset.add_synthetic_event(EventType.OWN_GOAL_FOR)
        second_run_ids = sorted(
            e.event_id for e in dataset.events
            if isinstance(e, OwnGoalForEvent)
        )

        assert first_run_ids == second_run_ids
        assert len(first_run_ids) >= 1, "fixture must have at least one own goal"
