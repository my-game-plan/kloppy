from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Optional, List

from kloppy.domain import (
    Event,
    Team,
    EventDataset,
    Point,
)
from kloppy.domain.models.event import (
    PossessionSwitchQualifier,
    PossessionSwitchType,
    SetPieceQualifier,
    SetPieceType,
    ShotEvent,
)
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

# ------------------------------------------------------------
# Spatial Utility Functions
# ------------------------------------------------------------
def is_own_half(event: Event) -> bool:
    """Check if the event is in the team's own half."""
    pitch_length = event.dataset.metadata.pitch_dimensions.x_dim.max
    return event.coordinates.x < pitch_length / 2


def is_own_third(event: Event) -> bool:
    """Check if the event is in the team's own third."""
    pitch_length = (event.dataset.metadata.pitch_dimensions.x_dim.max-event.dataset.metadata.pitch_dimensions.x_dim.min)
    return event.coordinates.x < pitch_length / 3

def is_attacking_third(event: Event) -> bool:
    """Check if the event is in the attacking third."""
    pitch_length = (event.dataset.metadata.pitch_dimensions.x_dim.max-event.dataset.metadata.pitch_dimensions.x_dim.min)
    return event.coordinates.x > 2 * (pitch_length / 3)


def close_to_goal(event: Event,) -> bool:
    """Distance to opponent goal under threshold."""
    dims = event.dataset.metadata.pitch_dimensions
    pitch_length = (dims.x_dim.max - dims.x_dim.min)*dims.pitch_length
    goal_point = Point(
        dims.x_dim.max,
        (dims.y_dim.max + dims.y_dim.min) / 2,
    )
    return dims.distance_between(Point(event.coordinates.x, event.coordinates.y), goal_point) < (pitch_length / 3)

# ------------------------------------------------------------
# Possession / Counter Attack Logic Helpers
# ------------------------------------------------------------
def find_last_possession_gain(event: Event, team: Team):
    """Walk backward to find the most recent possession gain for team."""
    cursor = event.prev_record

    while cursor and cursor.period == event.period:
        switch = cursor.get_qualifier_value(PossessionSwitchQualifier)
        if switch == PossessionSwitchType.GAIN and cursor.team == team:
            return cursor
        cursor = cursor.prev_record

    return None

def find_last_sequence_event_in_final_third(event: Event, team: Team):
    """Walk backward to find the last counter event in final third for team."""
    cursor = event.prev_record

    while cursor and cursor.period == event.period:
        other_sequence = cursor.state["sequence"].sequence_id and cursor.state["sequence"].sequence_id != event.state[
            "sequence"].sequence_id
        if other_sequence:
            break
        if is_possessing_event(cursor) and cursor.team == team and is_attacking_third(cursor):
            return cursor
        cursor = cursor.prev_record

    return None

def find_first_close_to_goal_event(event: Event, team: Team):
    """Walk forward until: close-to-goal condition OR turnover OR opponent gains ball."""
    cursor = event.next_record

    while cursor and cursor.period == event.period:
        switch = cursor.get_qualifier_value(PossessionSwitchQualifier)

        if switch == PossessionSwitchType.LOSE and cursor.team == team:
            return None  # turnover ends counter attempt

        if is_possessing_event(cursor):
            if cursor.team != team:
                return None  # opponent gains ball
            if close_to_goal(cursor):
                return cursor  # good event found

        cursor = cursor.next_record

    return None

def find_sustaining_event(event: Event, team: Team):
    """Look forward for another strong offensive action within close range."""
    cursor = event.next_record

    while cursor and cursor.period == event.period:
        if (
            is_possessing_event(cursor)
            and cursor.team == team
            and close_to_goal(cursor)
        ):
            return cursor
        cursor = cursor.next_record

    return None

def detect_counter_attack(event: Event, state: PhaseOfPlay):
    """
    Full counter-attack detection logic — cleanly isolated.
    Returns True if conditions satisfied, else False.
    """
    gain_event = find_last_possession_gain(event, state.team)
    if not gain_event or not is_own_half(gain_event):
        return False

    possession_gain_time = gain_event.timestamp
    gained_in_own_third = is_own_third(gain_event)

    close_goal_event = find_first_close_to_goal_event(event, state.team)
    if not close_goal_event:
        return False

    allowed_seconds = 20 if gained_in_own_third else 15
    if close_goal_event.timestamp - possession_gain_time > timedelta(seconds=allowed_seconds):
        return False

    # If shot happens immediately inside window → definite counter attack
    if isinstance(close_goal_event, ShotEvent):
        return True

    sustaining_event = find_sustaining_event(close_goal_event, state.team)
    if not sustaining_event:
        return False

    if sustaining_event.timestamp - close_goal_event.timestamp <= timedelta(seconds=15):
        return True

    return False

def determine_phase_change(
    event: Event,
    state: PhaseOfPlay
) -> Optional[PhaseOfPlayType]:
    """Determine if an event triggers a phase change."""

    if isinstance(event, EXCLUDED_OFF_BALL_EVENTS):
        return None

    set_piece_type = event.get_qualifier_value(SetPieceQualifier)
    if set_piece_type in (SetPieceType.GOAL_KICK, SetPieceType.KICK_OFF):
        return PhaseOfPlayType.BUILD_UP
    elif set_piece_type:
        return PhaseOfPlayType.SET_PLAY

    # ---------------- TRANSITION LOGIC ---------------- #
    if state.phase == PhaseOfPlayType.TRANSITION:
        # --- Counter Attack Detection --- #
        if detect_counter_attack(event, state):
            return PhaseOfPlayType.COUNTER_ATTACK

        # Re-check if transition should restart
        last_possession_event = event.prev_record
        while last_possession_event and not is_possessing_event(last_possession_event):
            last_possession_event = last_possession_event.prev_record

        if last_possession_event:
            switch = last_possession_event.get_qualifier_value(PossessionSwitchQualifier)
            if switch == PossessionSwitchType.GAIN:
                return PhaseOfPlayType.TRANSITION
        # Transition ends when two consecutive team possession actions occur
        same_team_prev = (
            last_possession_event
            and last_possession_event.team == event.team
            and is_possessing_event(last_possession_event)
        )
        if same_team_prev and is_possessing_event(event):
            return (
                PhaseOfPlayType.BUILD_UP
                if is_own_half(event)
                else PhaseOfPlayType.ESTABLISHED_POSSESSION
            )


    # ---------------- BUILD-UP LOGIC ------------------- #
    if state.phase == PhaseOfPlayType.BUILD_UP:
        possession_switch_type = event.get_qualifier_value(PossessionSwitchQualifier)
        if possession_switch_type == PossessionSwitchType.GAIN:
            return PhaseOfPlayType.TRANSITION

        # build up ends when ball goes over the halfway line
        if not is_own_half(event) and event.team == state.team:
            return PhaseOfPlayType.ESTABLISHED_POSSESSION


    # ------------ COUNTER ATTACK LOGIC ----------------- #
    if state.phase == PhaseOfPlayType.COUNTER_ATTACK:
        # check if counter attack becomes build_up again
        possession_switch_type = event.get_qualifier_value(PossessionSwitchQualifier)
        if possession_switch_type == PossessionSwitchType.GAIN:
            return PhaseOfPlayType.TRANSITION


        if is_own_half(event):
            last_final_third_event = find_last_sequence_event_in_final_third(event, state.team)
            if last_final_third_event and event.team == state.team:
                return PhaseOfPlayType.BUILD_UP

    # ---------------- ESTABLISHED POSSESSION ---------------- #
    if state.phase == PhaseOfPlayType.ESTABLISHED_POSSESSION:
        possession_switch_type = event.get_qualifier_value(PossessionSwitchQualifier)
        if possession_switch_type == PossessionSwitchType.GAIN:
            return PhaseOfPlayType.TRANSITION

        if event.team == state.team and is_own_half(event):
            return PhaseOfPlayType.BUILD_UP

    # -------------------- SET PLAY -------------------------- #
    if state.phase == PhaseOfPlayType.SET_PLAY:
        possession_switch_type = event.get_qualifier_value(PossessionSwitchQualifier)
        if possession_switch_type == PossessionSwitchType.GAIN:
            return PhaseOfPlayType.TRANSITION
        prev_event = event.prev_record

        if prev_event:
            prev_set_piece = prev_event.get_qualifier_value(SetPieceQualifier)
            same_team_prev = (
                prev_event.team == event.team
                and is_possessing_event(prev_event)
            )
            if not prev_set_piece and same_team_prev and is_possessing_event(event):
                return (
                    PhaseOfPlayType.BUILD_UP
                    if is_own_half(event)
                    else PhaseOfPlayType.ESTABLISHED_POSSESSION
                )

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
        first_team = dataset.events[0].team
        return PhaseOfPlay(phase=PhaseOfPlayType.BUILD_UP, team=first_team)

    def reduce_before(self, state: PhaseOfPlay, event: Event) -> PhaseOfPlay:
        """Update state before applying the event."""
        new_phase_type = determine_phase_change(event, state)
        if new_phase_type:
             state = replace(state, phase=new_phase_type, team=event.team)
        return state

    def reduce_after(self, state: PhaseOfPlay, event: Event) -> PhaseOfPlay:
        """Update state after applying the event."""
        return state

    def post_process(self, events: List[Event]):
        """Optional post-processing once all events have been assigned phases."""
        pass
