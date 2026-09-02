"""Unit tests for observation data models."""

from dataclasses import FrozenInstanceError

import pytest

from linkforge.browser.models import InteractiveElement
from linkforge.observation.models import Observation


def test_observation_stores_page_state() -> None:
    elements = (
        InteractiveElement(target_id=1, role="textbox", name="Search"),
        InteractiveElement(target_id=2, role="button", name="Submit"),
    )
    observation = Observation(
        url="https://example.com/page",
        title="Example Page",
        text="Page content",
        interactive_elements=elements,
    )

    assert observation.url == "https://example.com/page"
    assert observation.title == "Example Page"
    assert observation.text == "Page content"
    assert observation.interactive_elements == elements


def test_observation_is_immutable() -> None:
    observation = Observation(
        url="https://example.com",
        title="Example",
        text="Content",
        interactive_elements=(),
    )

    with pytest.raises(FrozenInstanceError):
        observation.title = "Changed"
