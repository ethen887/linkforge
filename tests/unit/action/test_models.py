"""Unit tests for action data models."""

from dataclasses import FrozenInstanceError

import pytest

from linkforge.action.models import (
    Action,
    ClickAction,
    FillAction,
    OpenAction,
    PressAction,
    ScrollAction,
)


def test_open_action_stores_url() -> None:
    action = OpenAction(url="https://example.com")

    assert action.url == "https://example.com"


def test_click_action_stores_target_id() -> None:
    action = ClickAction(target_id=3)

    assert action.target_id == 3


def test_fill_action_stores_target_id_and_text() -> None:
    action = FillAction(target_id=1, text="LinkForge")

    assert action.target_id == 1
    assert action.text == "LinkForge"


def test_press_action_stores_target_id_and_key() -> None:
    action = PressAction(target_id=1, key="Enter")

    assert action.target_id == 1
    assert action.key == "Enter"


def test_scroll_action_stores_delta() -> None:
    action = ScrollAction(delta_y=500)

    assert action.delta_y == 500


@pytest.mark.parametrize(
    ("action", "field", "value"),
    [
        (OpenAction(url="https://example.com"), "url", "https://changed.example.com"),
        (ClickAction(target_id=3), "target_id", 4),
        (FillAction(target_id=1, text="LinkForge"), "text", "Changed"),
        (PressAction(target_id=1, key="Enter"), "key", "Escape"),
        (ScrollAction(delta_y=500), "delta_y", 100),
    ],
)
def test_actions_are_immutable(action: Action, field: str, value: object) -> None:
    with pytest.raises(FrozenInstanceError):
        setattr(action, field, value)
