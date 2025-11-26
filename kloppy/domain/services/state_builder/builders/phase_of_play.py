from dataclasses import dataclass, replace
from typing import Optional, List

from kloppy.domain import (
    Event,
    Team,
    EventDataset,
)
from kloppy.domain.models.event import PossessionSwitchQualifier, PossessionSwitchType, EventType, SetPieceQualifier, \
    SetPieceType
from .sequence import is_possessing_event, EXCLUDED_OFF_BALL_EVENTS
from ..builder import StateBuilder

from enum import Enum


class PhaseOfPlayType(Enum):
    TRANSITION = "transition"
    BUILD_UP = "build_up"
    COUNTER_ATTACK = "counter_attack"
    ESTABLISHED_POSSESSION = "established_possession"
    SET_PLAY = "set_play"

@dataclass
class PhaseOfPlay:
    phase: PhaseOfPlayType
    team: Optional[Team]

def is_own_half(event) -> bool:
    """Check if the event is in the team's own half."""
    pitch_length = event.dataset.metadata.pitch_dimensions.x_dim.max
    return event.coordinates.x < pitch_length / 2

def determine_phase_change(
    event: Event,
    state: PhaseOfPlay
) -> Optional[PhaseOfPlayType]:
    """
    Determine if the given event causes a phase-of-play transition.
    Returns the *new* phase if a change should occur, otherwise returns the existing one.
    """
    if isinstance(event, EXCLUDED_OFF_BALL_EVENTS):
        return None

    set_piece_type = event.get_qualifier_value(SetPieceQualifier)
    if set_piece_type and set_piece_type not in [SetPieceType.GOAL_KICK, SetPieceType.KICK_OFF]:
        return PhaseOfPlayType.SET_PLAY

    # --- TRANSITION LOGIC ---
    if state.phase == PhaseOfPlayType.TRANSITION:
        # transition ends when 2 possession actions from same team happen
        prev_event = event.prev_record
        possession_switch_type = prev_event.get_qualifier_value(PossessionSwitchQualifier)
        if possession_switch_type == PossessionSwitchType.GAIN:
            return None

        same_team_possessing_event = prev_event and prev_event.team == event.team and is_possessing_event(prev_event)
        if is_possessing_event(event) and same_team_possessing_event:
            if is_own_half(event):
                return PhaseOfPlayType.BUILD_UP
            else:
                return PhaseOfPlayType.ESTABLISHED_POSSESSION


    # --- BUILD-UP LOGIC ---
    if state.phase == PhaseOfPlayType.BUILD_UP:
        possession_switch_type = event.get_qualifier_value(PossessionSwitchQualifier)
        if possession_switch_type == PossessionSwitchType.GAIN:
            return PhaseOfPlayType.TRANSITION
        # build up ends when ball goes over the halfway line
        if not is_own_half(event) and event.team == state.team:
            return PhaseOfPlayType.ESTABLISHED_POSSESSION


    # --- COUNTER ATTACK LOGIC ---
    if state.phase == PhaseOfPlayType.COUNTER_ATTACK:
        # placeholder: check if counter attack becomes established possession
        # placeholder: check if counter attack ends
        pass

    # --- ESTABLISHED POSSESSION LOGIC ---
    if state.phase == PhaseOfPlayType.ESTABLISHED_POSSESSION:
        # possession loss: established possession → transition
        possession_switch_type = event.get_qualifier_value(PossessionSwitchQualifier)
        if possession_switch_type == PossessionSwitchType.GAIN:
            return PhaseOfPlayType.TRANSITION
        if is_own_half(event) and event.team == state.team:
            # ball goes back into own half → build up
            return PhaseOfPlayType.BUILD_UP

    # --- SET PLAY LOGIC ---
    if state.phase == PhaseOfPlayType.SET_PLAY:
        prev_event = event.prev_record
        set_piece_type = event.get_qualifier_value(SetPieceQualifier)
        same_team_possessing_event = prev_event and prev_event.team == event.team and is_possessing_event(prev_event)
        if not set_piece_type and is_possessing_event(event) and same_team_possessing_event:
            if is_own_half(event):
                return PhaseOfPlayType.BUILD_UP
            else:
                return PhaseOfPlayType.ESTABLISHED_POSSESSION

    # Default: stay in the same phase
    return None



def determine_phase_end(event: Event, state: PhaseOfPlay) -> bool:
    """Return True if the current phase should end."""
    pass


def classify_phase(event: Event, state: PhaseOfPlay) -> Optional[str]:
    """Return the phase name for this event (buildup, transition, etc)."""
    pass


# ----------------------------------------------------------------------
# State Builder Skeleton
# ----------------------------------------------------------------------

class PhaseOfPlayStateBuilder(StateBuilder):

    def initial_state(self, dataset: EventDataset) -> PhaseOfPlay:
        """Determine initial phase before the first event."""
        return PhaseOfPlay(phase=PhaseOfPlayType.BUILD_UP, team=dataset.events[0].team)

    def reduce_before(self, state: PhaseOfPlay, event: Event) -> PhaseOfPlay:
        """Update state before applying the event."""
        # Example flow (to be implemented):
        new_phase_type = determine_phase_change(event, state)
        if new_phase_type:
             state = replace(state, phase=new_phase_type, team=event.team)
        return state

    def reduce_after(self, state: PhaseOfPlay, event: Event) -> PhaseOfPlay:
        """Update state after applying the event."""
        # Example flow (to be implemented):
        # if determine_phase_end(...):
        #     state = replace(state, phase=None, team=None)
        return state

    def post_process(self, events: List[Event]):
        """Optional post-processing once all events have been assigned phases."""
        # Placeholder for any cleanup or annotation logic
        pass
