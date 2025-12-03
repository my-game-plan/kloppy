import json
from collections import defaultdict
from itertools import groupby

from kloppy import statsbomb, statsperform
from kloppy.domain import Event, EventDataset, EventType, FormationType
from kloppy.domain.models.event import PossessionSwitchQualifier, PossessionSwitchType
from kloppy.domain.services.state_builder.builder import StateBuilder
from kloppy.domain.services.state_builder.builders.phase_of_play import PhaseOfPlay, PhaseOfPlayType
from kloppy.utils import performance_logging


class TestStateBuilder:
    """"""

    def _load_dataset_statsbomb(self, base_dir, base_filename="statsbomb"):
        return statsbomb.load(
            event_data=base_dir / f"files/{base_filename}_event.json",
            lineup_data=base_dir / f"files/{base_filename}_lineup.json",
        )

    def _load_dataset_statsperform(
        self, base_dir, base_filename="statsperform"
    ):
        return statsperform.load_event(
            ma1_data=base_dir / f"files/{base_filename}_event_ma1.json",
            ma3_data=base_dir / f"files/{base_filename}_event_ma3.json",
        )

    def test_score_state_builder(self, base_dir):
        dataset = self._load_dataset_statsbomb(base_dir)

        with performance_logging("add_state"):
            dataset_with_state = dataset.add_state("score")

        events_per_score = {}
        for score, events in groupby(
            dataset_with_state.events, lambda event: event.state["score"]
        ):
            events = list(events)
            events_per_score[str(score)] = len(events)

        assert events_per_score == {
            "0-0": 2928,
            "1-0": 719,
            "2-0": 405,
            "3-0": 7,
            "3-1": 2,
        }

    def test_sequence_state_builder_statsbomb(self, base_dir):
        dataset = self._load_dataset_statsbomb(base_dir)

        with performance_logging("add_state"):
            dataset_with_state = dataset.add_state("sequence")

        events_per_sequence = defaultdict(int)
        poss_switch = {PossessionSwitchType.LOSE: [], PossessionSwitchType.GAIN: []}
        for sequence_id, events in groupby(
            dataset_with_state,
            lambda event: event.state["sequence"].sequence_id,
        ):
            events = list(events)
            events_per_sequence[sequence_id] += len(events)
            for e in events:
                if e.get_qualifier_value(PossessionSwitchQualifier):
                    poss_switch[e.get_qualifier_value(PossessionSwitchQualifier)].append(e.event_type)

        assert events_per_sequence[1] == 3
        assert events_per_sequence[72] == 12
        assert len(poss_switch[PossessionSwitchType.GAIN]) == 152
        assert len(poss_switch[PossessionSwitchType.LOSE]) == 155

    def test_sequence_state_builder_statsperform(self, base_dir):
        dataset = self._load_dataset_statsperform(base_dir)

        with performance_logging("add_state"):
            dataset_with_state = dataset.add_state("sequence")

        events_per_sequence = defaultdict(int)
        poss_switch = {PossessionSwitchType.LOSE: [], PossessionSwitchType.GAIN: []}

        for sequence_id, events in groupby(
            [e for e in dataset_with_state.events if e.state["sequence"].sequence_id is not None],
            lambda event: event.state["sequence"].sequence_id,
        ):
            events = list(events)

            for e in events:
                if e.get_qualifier_value(PossessionSwitchQualifier):
                    poss_switch[e.get_qualifier_value(PossessionSwitchQualifier)].append(e.event_type)

            events_per_sequence[sequence_id] += len(events)

        assert events_per_sequence[1] == 5
        assert events_per_sequence[89] == 12
        assert len(poss_switch[PossessionSwitchType.GAIN]) == 143
        assert len(poss_switch[PossessionSwitchType.LOSE]) == 174

    def test_lineup_state_builder(self, base_dir):
        dataset = self._load_dataset_statsbomb(
            base_dir, base_filename="statsbomb_15986"
        )

        with performance_logging("add_state"):
            dataset_with_state = dataset.add_state("lineup")

        last_events = []
        for lineup, events in groupby(
            dataset_with_state.events, lambda event: event.state["lineup"]
        ):
            events = list(events)
            # inspect last event which changed the lineup
            last_events.append((events[-1].event_type, len(lineup.players)))

        assert last_events == [
            (EventType.CARD, 22),
            (EventType.SUBSTITUTION, 21),
            (EventType.SUBSTITUTION, 21),
            (EventType.SUBSTITUTION, 21),
            (EventType.SUBSTITUTION, 21),
            (EventType.SUBSTITUTION, 21),
            (EventType.SUBSTITUTION, 21),
            (EventType.GENERIC, 21),
        ]

    def test_formation_state_builder(self, base_dir):
        dataset = self._load_dataset_statsbomb(
            base_dir, base_filename="statsbomb"
        )

        with performance_logging("add_state"):
            dataset_with_state = dataset.add_state("formation")

        events_per_formation_change = {}
        for formation, events in groupby(
            dataset_with_state.events,
            lambda event: event.state["formation"].away,
        ):
            events = list(events)
            events_per_formation_change[str(formation)] = len(events)

        # inspect FormationChangeEvent usage and formation state_builder
        assert events_per_formation_change["4-1-4-1"] == 3104
        assert events_per_formation_change["4-4-2"] == 957

        assert dataset.metadata.teams[0].starting_formation == FormationType(
            "4-4-2"
        )
        assert dataset_with_state.events[1].state[
            "formation"
        ].home == FormationType("4-4-2")

    def test_register_custom_builder(self, base_dir):
        class CustomStateBuilder(StateBuilder):
            def initial_state(self, dataset: EventDataset) -> int:
                return 0

            def reduce_before(self, state: int, event: Event) -> int:
                return state + 1

            def reduce_after(self, state: int, event: Event) -> int:
                return state + 1

        dataset = self._load_dataset_statsbomb(
            base_dir, base_filename="statsbomb_15986"
        )

        with performance_logging("add_state"):
            dataset_with_state = dataset.add_state("custom")

        assert dataset_with_state.events[0].state["custom"] == 1
        assert dataset_with_state.events[1].state["custom"] == 3
        assert dataset_with_state.events[2].state["custom"] == 5
        assert dataset_with_state.events[3].state["custom"] == 7

    def test_phase_of_play_state_builder_statsbomb(self, base_dir):
        dataset = self._load_dataset_statsbomb(base_dir)

        with performance_logging("add_state"):
            dataset_with_state = dataset.add_state("sequence","phase_of_play")
        events = dataset_with_state.events
        for event in events:
            assert event.state["phase_of_play"] is not None

        build_up_event = dataset_with_state.get_event_by_id("ce508a95-38d3-4248-a50e-dc8d7e23230c")
        assert build_up_event.state["phase_of_play"] == PhaseOfPlay(
            phase=PhaseOfPlayType.BUILD_UP,
            team=build_up_event.team
        )

        transition_event = dataset_with_state.get_event_by_id("f1cc47d6-4b19-45a6-beb9-33d67fc83f4b")
        assert transition_event.state["phase_of_play"] == PhaseOfPlay(
            phase=PhaseOfPlayType.TRANSITION,
            team=transition_event.team
        )

        established_possession_event = dataset_with_state.get_event_by_id("d2d49535-0037-4b01-9d4c-7715dbb58665")
        assert established_possession_event.state["phase_of_play"] == PhaseOfPlay(
            phase=PhaseOfPlayType.ESTABLISHED_POSSESSION,
            team=established_possession_event.team
        )

        counter_attack_event = dataset_with_state.get_event_by_id("72356e49-b224-450d-9a25-fb09e3627ab2")
        assert counter_attack_event.state["phase_of_play"] == PhaseOfPlay(
            phase=PhaseOfPlayType.COUNTER_ATTACK,
            team=counter_attack_event.team
        )

        set_play_event = dataset_with_state.get_event_by_id("66974d44-2bbe-4b87-abd1-601123630c79")
        assert set_play_event.state["phase_of_play"] == PhaseOfPlay(
            phase=PhaseOfPlayType.SET_PLAY,
            team=set_play_event.team
        )

