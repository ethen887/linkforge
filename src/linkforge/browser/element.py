"""Provider-neutral, document-bound DOM elements for deterministic adapters."""

from typing import Protocol


class BrowserElement(Protocol):
    """Valid only inside its Browser.element_scope context.

    Elements refer to the captured DOM nodes, never silently retarget replacements.
    All operation failures raise BrowserError. Scripts and selectors are trusted
    application code, never model-generated browser instructions.
    """

    def query_all(self, selector: str) -> tuple["BrowserElement", ...]:
        """Return descendants in DOM order, scoped to this element."""
        ...

    def evaluate(self, expression: str) -> object:
        """Evaluate a trusted expression with this element as its argument."""
        ...

    def screenshot(self) -> bytes:
        """Scroll into view, then capture this element as in-memory PNG bytes."""
        ...

    def click(self) -> None:
        """Perform a normal actionable DOM click."""
        ...
