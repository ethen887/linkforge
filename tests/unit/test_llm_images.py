"""Images survive provider conversion; legacy text remains unchanged."""

import base64

import pytest

from linkforge.llm.anthropic import AnthropicInterface
from linkforge.llm.base import LLMImage, LLMMessage
from linkforge.llm.openai import OpenAIInterface


@pytest.mark.parametrize("adapter", [OpenAIInterface, AnthropicInterface])
def test_image_bytes_reach_wire_message(adapter):
    image = LLMImage(b"png-data")
    message = LLMMessage(role="user", content="question", images=(image,))
    converted = adapter.__new__(adapter)._convert_message(message)
    assert converted["content"][0] == {"type": "text", "text": "question"}
    block = converted["content"][1]
    if adapter is OpenAIInterface:
        assert block["type"] == "image_url"
        prefix, data = block["image_url"]["url"].split(",", 1)
        assert prefix == "data:image/png;base64"
    else:
        assert block["type"] == "image"
        assert block["source"]["type"] == "base64"
        assert block["source"]["media_type"] == "image/png"
        data = block["source"]["data"]
    assert base64.b64decode(data) == image.data
    assert "png-data" not in repr(message)


@pytest.mark.parametrize("role", ["system", "assistant", "tool"])
def test_images_reject_unsupported_roles(role):
    with pytest.raises(ValueError, match="user messages"):
        LLMMessage(role=role, images=(LLMImage(b"png"),))


@pytest.mark.parametrize(
    "data,media_type", [(b"", "image/png"), ("text", "image/png"), (b"x", "text/plain")]
)
def test_invalid_image_rejected(data, media_type):
    with pytest.raises(ValueError):
        LLMImage(data, media_type)
