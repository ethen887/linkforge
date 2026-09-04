from __future__ import annotations

import time
from dataclasses import dataclass

from linkforge.application.task_runner import TaskType
from linkforge.browser.exceptions import BrowserError
from linkforge.browser.playwright import PlaywrightBrowser
from linkforge.platforms.chaoxing.task_detector import ChaoxingTaskDetector


PHYSICS_URL = (
    "https://mooc1.chaoxing.com/mycourse/studentstudy?"
    "chapterId=1120195391&courseId=260810626&clazzid=140199897"
    "&cpi=498300787&enc=abcf4009e2208a926d3db17a786067f6"
    "&mooc2=1&hidetype=0&openc=8cf3ef849e9639ea353d4463ea5a5cd9"
)

SECOND_COURSE_URL = (
    "https://mooc1.chaoxing.com/mycourse/studentstudy?"
    "chapterId=1024780735&courseId=254390389&clazzid=128354731"
    "&cpi=498300787&enc=f2486900c8f6763ba93263c7ebd0803b"
    "&mooc2=1&hidetype=0&openc=e07882b9c222a6a4c9bda0474b085ec3"
)

QUIZ_URL = (
    "https://mooc1.chaoxing.com/mycourse/studentstudy?"
    "chapterId=1120195788&courseId=260810626&clazzid=140199897"
    "&cpi=498300787&enc=abcf4009e2208a926d3db17a786067f6"
    "&mooc2=1&hidetype=0&openc=8cf3ef849e9639ea353d4463ea5a5cd9"
)

DOCUMENT_URL = (
    "https://mooc1.chaoxing.com/mycourse/studentstudy?"
    "chapterId=1120195428&courseId=260810626&clazzid=140199897"
    "&cpi=498300787&enc=abcf4009e2208a926d3db17a786067f6"
    "&mooc2=1&hidetype=0&openc=8cf3ef849e9639ea353d4463ea5a5cd9"
)

SETTLE_SECONDS = 5.0
VIDEO_SAMPLE_INTERVAL = 0.5
VIDEO_SAMPLE_COUNT = 10
TRANSITION_ROUNDS = 3


@dataclass(frozen=True, slots=True)
class CheckResult:
    label: str
    passed: bool
    expected: str
    actual: str


class MonitoringPlaywrightBrowser(PlaywrightBrowser):
    """Track BrowserError failures from production frame inspection."""

    def __init__(
        self,
        *,
        headless: bool = False,
        timeout_ms: int = 15_000,
    ) -> None:
        super().__init__(headless=headless, timeout_ms=timeout_ms)
        self.inspection_calls = 0
        self.inspection_browser_errors = 0

    def evaluate_in_frames(self, expression: str) -> tuple[object, ...]:
        self.inspection_calls += 1

        try:
            return super().evaluate_in_frames(expression)
        except BrowserError:
            self.inspection_browser_errors += 1
            raise


def record_exact(
    results: list[CheckResult],
    detector: ChaoxingTaskDetector,
    *,
    label: str,
    expected: TaskType,
) -> None:
    actual = detector.detect()
    passed = actual is expected

    results.append(
        CheckResult(
            label=label,
            passed=passed,
            expected=expected.name,
            actual=actual.name,
        )
    )

    print(
        f"{'PASS' if passed else 'FAIL'} | "
        f"{label:<42} | expected={expected.name:<8} actual={actual.name}"
    )


def verify_video_transition(
    results: list[CheckResult],
    detector: ChaoxingTaskDetector,
    *,
    round_number: int,
) -> None:
    """
    Verify the dynamic Video transition.

    This real video is already completed, but Chaoxing may briefly expose it as
    unfinished before ans-job-finished is synchronized.

    Acceptance rules:
    - UNKNOWN must never appear.
    - Intermediate VIDEO is allowed.
    - The state must eventually stabilize to CONTENT.
    """
    observed: list[TaskType] = []

    for _ in range(VIDEO_SAMPLE_COUNT):
        time.sleep(VIDEO_SAMPLE_INTERVAL)
        observed.append(detector.detect())

    no_unknown = TaskType.UNKNOWN not in observed
    eventual_content = observed[-1] is TaskType.CONTENT

    sequence = " -> ".join(item.name for item in observed)

    results.append(
        CheckResult(
            label=f"Round {round_number} / Video transition: no UNKNOWN",
            passed=no_unknown,
            expected="VIDEO/CONTENT only",
            actual=sequence,
        )
    )

    results.append(
        CheckResult(
            label=f"Round {round_number} / Video final stable state",
            passed=eventual_content,
            expected=TaskType.CONTENT.name,
            actual=observed[-1].name,
        )
    )

    print(
        f"{'PASS' if no_unknown else 'FAIL'} | "
        f"Round {round_number} / Video transition"
    )
    print(f"       observed: {sequence}")

    print(
        f"{'PASS' if eventual_content else 'FAIL'} | "
        f"Round {round_number} / Video final state "
        f"| expected=CONTENT actual={observed[-1].name}"
    )


def print_summary(
    results: list[CheckResult],
    browser: MonitoringPlaywrightBrowser,
) -> None:
    print("\n" + "=" * 100)
    print("FINAL ACCEPTANCE SUMMARY")
    print("=" * 100)

    for result in results:
        print(
            f"{'PASS' if result.passed else 'FAIL'} | "
            f"{result.label:<46} | "
            f"expected={result.expected} | actual={result.actual}"
        )

    passed = sum(result.passed for result in results)
    total = len(results)

    browser_ok = browser.inspection_browser_errors == 0

    print("\n" + "-" * 100)
    print(f"Functional checks:          {passed}/{total} passed")
    print(f"Frame inspection calls:     {browser.inspection_calls}")
    print(f"Frame inspection errors:    {browser.inspection_browser_errors}")
    print(
        "Detached-frame regression: "
        f"{'PASS' if browser_ok else 'FAIL'} "
        "(no BrowserError escaped production frame inspection)"
    )

    overall = passed == total and browser_ok

    print("\n" + "=" * 100)
    print(
        "ChaoxingTaskDetector V1 REAL ACCEPTANCE: "
        f"{'PASS' if overall else 'FAIL'}"
    )
    print("=" * 100)

    if not overall:
        print("Do not commit yet. Send the complete terminal output for review.")


def main() -> None:
    browser = MonitoringPlaywrightBrowser(
        headless=False,
        timeout_ms=20_000,
    )
    detector = ChaoxingTaskDetector(browser)
    results: list[CheckResult] = []

    print("ChaoxingTaskDetector V1 - real acceptance smoke")
    print("=" * 100)
    print("Goals:")
    print("  1. Verify CONTENT / DOCUMENT / QUIZ on real Chaoxing pages.")
    print("  2. Repeatedly stress Overview -> PPT -> Video frame replacement.")
    print("  3. Verify no transient UNKNOWN / BrowserError during Video transition.")
    print("  4. Verify the already-finished Video eventually stabilizes to CONTENT.")
    print()
    print("No LLM. No course submission. No production code changes.")

    browser.start()

    try:
        browser.open(PHYSICS_URL)

        print("\n如需要登录，请在 Chromium 中完成登录。")
        input("确认已登录且课程页正常显示后，按 Enter。之后测试自动运行...")

        # Repeated transitions deliberately exercise dynamic iframe destruction
        # and recreation, which previously caused "Frame was detached".
        for round_number in range(1, TRANSITION_ROUNDS + 1):
            print("\n" + "=" * 100)
            print(f"TRANSITION ROUND {round_number}/{TRANSITION_ROUNDS}")
            print("=" * 100)

            browser.open(PHYSICS_URL)
            time.sleep(SETTLE_SECONDS)

            record_exact(
                results,
                detector,
                label=f"Round {round_number} / Overview",
                expected=TaskType.CONTENT,
            )

            browser.click("#prev_tab li:nth-child(2)")
            time.sleep(SETTLE_SECONDS)

            record_exact(
                results,
                detector,
                label=f"Round {round_number} / PPT",
                expected=TaskType.DOCUMENT,
            )

            browser.click("#prev_tab li:nth-child(3)")

            verify_video_transition(
                results,
                detector,
                round_number=round_number,
            )

        print("\n" + "=" * 100)
        print("OTHER REAL SAMPLES")
        print("=" * 100)

        browser.open(SECOND_COURSE_URL)
        time.sleep(SETTLE_SECONDS)
        record_exact(
            results,
            detector,
            label="All special modules already finished",
            expected=TaskType.CONTENT,
        )

        browser.open(QUIZ_URL)
        time.sleep(SETTLE_SECONDS)
        record_exact(
            results,
            detector,
            label="Quiz / work module",
            expected=TaskType.QUIZ,
        )

        browser.open(DOCUMENT_URL)
        time.sleep(SETTLE_SECONDS)
        record_exact(
            results,
            detector,
            label="Document / summary PDF",
            expected=TaskType.DOCUMENT,
        )

        print_summary(results, browser)

        input("\n按 Enter 关闭 Chromium...")

    finally:
        browser.close()


if __name__ == "__main__":
    main()
