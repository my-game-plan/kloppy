from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Optional, List

from kloppy.domain import (
    Event,
    Team,
    EventDataset,
    Point,
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

def close_to_goal(event) -> bool:
    distance = event.dataset.metadata.pitch_dimensions.distance_between(
        Point(event.coordinates.x, event.coordinates.y),
        Point(event.dataset.metadata.pitch_dimensions.x_dim.max,
              (event.dataset.metadata.pitch_dimensions.y_dim.max
            + event.dataset.metadata.pitch_dimensions.y_dim.min
              ) / 2))
    return (distance < 35)

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
    if set_piece_type in [SetPieceType.GOAL_KICK, SetPieceType.KICK_OFF]:
        return PhaseOfPlayType.BUILD_UP
    elif set_piece_type:
        return PhaseOfPlayType.SET_PLAY

    # --- TRANSITION LOGIC ---
    if state.phase == PhaseOfPlayType.TRANSITION:
        # Check if transition goes over into counter attack
        prev_poss_gain_timestamp = None
        _counter_prev = event.prev_record

        while prev_poss_gain_timestamp is None:
            if not _counter_prev or _counter_prev.period != event.period:
                break

            possession_switch_type = _counter_prev.get_qualifier_value(PossessionSwitchQualifier)
            if possession_switch_type == PossessionSwitchType.GAIN and _counter_prev.team == state.team:
                if is_own_half(_counter_prev):
                    prev_poss_gain_timestamp = _counter_prev.timestamp
                break
            else:
                _counter_prev = _counter_prev.prev_record
        if prev_poss_gain_timestamp:
            # Spatial Condition: The distance between the ball and the goal of the ball losing team is reduced to less than d=35 m
            close_to_goal_timestamp = None
            _counter_next = event.next_record
            while close_to_goal_timestamp is None:
                if not _counter_next or _counter_next.period != event.period:
                    break
                # stop if possession loss from team occurs
                possession_switch_type = _counter_next.get_qualifier_value(PossessionSwitchQualifier)
                if possession_switch_type == PossessionSwitchType.LOSE and _counter_next.team == event.team:
                    break
                if is_possessing_event(_counter_next) and _counter_next.team != state.team:
                    break
                elif is_possessing_event(_counter_next) and _counter_next.team == state.team and close_to_goal(_counter_next):
                    close_to_goal_timestamp = _counter_next.timestamp
                    break
                else:
                    _counter_next = _counter_next.next_record

            # Temporal Condition: The spatial criterion is met within a time window of t3 = 15s after the turnover (possession gain)
            if close_to_goal_timestamp and close_to_goal_timestamp - prev_poss_gain_timestamp <= timedelta(seconds=15):

                # Sustain Possession Condition: After the spatial criterion is met there is another offensive event (shot, pass, carry or dribble)
                # of the ball winning team with a distance of less than d = 35m within the next t4 = 5s.
                sustain_possession_timestamp = None
                _counter_next2 = _counter_next.next_record
                while sustain_possession_timestamp is None:
                    if is_possessing_event(_counter_next2) and _counter_next.team == _counter_next2.team and close_to_goal(_counter_next2):
                        sustain_possession_timestamp = _counter_next2.timestamp
                        break
                    else:
                        _counter_next2 = _counter_next2.next_record
                if sustain_possession_timestamp and sustain_possession_timestamp - close_to_goal_timestamp <= timedelta(seconds=15):
                    return PhaseOfPlayType.COUNTER_ATTACK


        prev_possession_event = event.prev_record
        while prev_possession_event and not is_possessing_event(prev_possession_event):
            prev_possession_event = prev_possession_event.prev_record
        possession_switch_type = prev_possession_event.get_qualifier_value(PossessionSwitchQualifier)
        if possession_switch_type == PossessionSwitchType.GAIN:
            return PhaseOfPlayType.TRANSITION

        # transition ends when 2 possession actions from same team happen
        same_team_possessing_event = prev_possession_event and prev_possession_event.team == event.team and is_possessing_event(prev_possession_event)
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
        possession_switch_type = event.get_qualifier_value(PossessionSwitchQualifier)
        if possession_switch_type == PossessionSwitchType.GAIN:
            return PhaseOfPlayType.TRANSITION

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
        set_piece_type = prev_event.get_qualifier_value(SetPieceQualifier)
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
