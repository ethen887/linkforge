"""Unit tests for observation data models."""

from dataclasses import FrozenInstanceError

import pytest

from linkforge.observation.models import Observation


def test_observation_stores_page_state() -> None:
    observation = Observation(
        url="https://example.com/page",
        title="Example Page",
        text="Page content",
    )

    assert observation.url == "https://example.com/page"
    assert observation.title == "Example Page"
    assert observation.text == "Page content"


def test_observation_is_immutable() -> None:
    observation = Observation(
        url="https://example.com",
        title="Example",
        text="Content",
    )

    with pytest.raises(FrozenInstanceError):
        observation.title = "Changed"
