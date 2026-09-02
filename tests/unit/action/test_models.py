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


def test_click_action_stores_selector() -> None:
    action = ClickAction(selector="#submit")

    assert action.selector == "#submit"


def test_fill_action_stores_selector_and_text() -> None:
    action = FillAction(selector="#name", text="LinkForge")

    assert action.selector == "#name"
    assert action.text == "LinkForge"


def test_press_action_stores_selector_and_key() -> None:
    action = PressAction(selector="#name", key="Enter")

    assert action.selector == "#name"
    assert action.key == "Enter"


def test_scroll_action_stores_delta() -> None:
    action = ScrollAction(delta_y=500)

    assert action.delta_y == 500


@pytest.mark.parametrize(
    ("action", "field", "value"),
    [
        (OpenAction(url="https://example.com"), "url", "https://changed.example.com"),
        (ClickAction(selector="#submit"), "selector", "#changed"),
        (FillAction(selector="#name", text="LinkForge"), "text", "Changed"),
        (PressAction(selector="#name", key="Enter"), "key", "Escape"),
        (ScrollAction(delta_y=500), "delta_y", 100),
    ],
)
def test_actions_are_immutable(action: Action, field: str, value: object) -> None:
    with pytest.raises(FrozenInstanceError):
        setattr(action, field, value)
