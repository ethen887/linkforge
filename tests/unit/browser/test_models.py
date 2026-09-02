"""Unit tests for browser-neutral data models."""

from dataclasses import FrozenInstanceError

import pytest

from linkforge.browser.models import InteractiveElement


def test_interactive_element_stores_agent_visible_state() -> None:
    element = InteractiveElement(target_id=3, role="button", name="Login")

    assert element.target_id == 3
    assert element.role == "button"
    assert element.name == "Login"


def test_interactive_element_is_immutable() -> None:
    element = InteractiveElement(target_id=3, role="button", name="Login")

    with pytest.raises(FrozenInstanceError):
        element.name = "Changed"
