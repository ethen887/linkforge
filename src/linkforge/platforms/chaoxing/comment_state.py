"""Session-scoped state for optimistic Chaoxing comment attempts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from urllib.parse import parse_qs, urlparse

from linkforge.platforms.chaoxing.models import ChaoxingPageState

COMMENT_MODULE_PATH = "/ananas/modules/insertbbs/"


class CommentOutcome(Enum):
    """A local handling result; none claims platform-confirmed publication."""

    ATTEMPTED_UNVERIFIED = "attempted_unverified"
    SUBMISSION_UNKNOWN = "submission_unknown"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class CommentIdentity:
    """A discussion identity bound to course, account context, knowledge and Card."""

    account_context: str
    course_id: str
    class_id: str
    knowledge_id: str
    card_index: int
    module_index: int
    module_path: str


@dataclass(frozen=True, slots=True)
class CommentRecord:
    identity: CommentIdentity
    outcome: CommentOutcome
    stage: str
    reason: str | None = None


class CommentIdentityError(RuntimeError):
    """The current discussion cannot be identified without ambiguity."""


class CommentAccountChangedError(CommentIdentityError):
    """A session record was reused after the account context changed."""


class CommentSession:
    """In-memory, per-application-run record shared by detector and handlers."""

    def __init__(self) -> None:
        self._account_context: str | None = None
        self._records: dict[CommentIdentity, CommentRecord] = {}

    def is_handled(self, identity: CommentIdentity) -> bool:
        self._bind_account(identity.account_context)
        return identity in self._records

    def record(
        self,
        identity: CommentIdentity,
        outcome: CommentOutcome,
        *,
        stage: str,
        reason: str | None = None,
    ) -> CommentRecord:
        self._bind_account(identity.account_context)
        item = CommentRecord(identity=identity, outcome=outcome, stage=stage, reason=reason)
        self._records[identity] = item
        return item

    def get(self, identity: CommentIdentity) -> CommentRecord | None:
        self._bind_account(identity.account_context)
        return self._records.get(identity)

    def _bind_account(self, account_context: str) -> None:
        if self._account_context is None:
            self._account_context = account_context
        elif self._account_context != account_context:
            raise CommentAccountChangedError(
                "Chaoxing account context changed during a comment handling session."
            )


def comment_identity(
    course_url: str,
    state: ChaoxingPageState,
    module_index: int,
) -> CommentIdentity:
    """Build a strict course-side identity without depending on a popup topic ID."""
    if state.knowledge_id is None:
        raise CommentIdentityError("The Chaoxing knowledge identity is unavailable.")
    if module_index < 0 or module_index >= len(state.modules):
        raise CommentIdentityError("The Chaoxing comment module index is invalid.")
    module_path = urlparse(state.modules[module_index].url).path
    if COMMENT_MODULE_PATH not in module_path:
        raise CommentIdentityError("The selected Chaoxing module is not an insertbbs discussion.")

    values = _routing_values(course_url)
    return CommentIdentity(
        account_context=_required(values, "cpi"),
        course_id=_required(values, "courseid"),
        class_id=_required(values, "clazzid", alias="classid"),
        knowledge_id=state.knowledge_id,
        card_index=state.active_tab_index,
        module_index=module_index,
        module_path=module_path,
    )


def _routing_values(url: str) -> dict[str, list[str]]:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if "?" in parsed.fragment:
        query.update(parse_qs(parsed.fragment.partition("?")[2]))
    return {key.lower(): values for key, values in query.items()}


def _required(values: dict[str, list[str]], key: str, *, alias: str | None = None) -> str:
    items = values.get(key, [])
    if not items and alias is not None:
        items = values.get(alias, [])
    if len(items) != 1 or not items[0].strip():
        raise CommentIdentityError(f"Chaoxing routing value is missing or ambiguous: {key}")
    return items[0]
