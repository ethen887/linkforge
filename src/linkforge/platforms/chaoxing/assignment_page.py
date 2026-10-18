"""独立发布的学习通作业页面身份与 DOM 就绪检查。"""

from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlsplit

from linkforge.browser.base import Browser
from linkforge.platforms.chaoxing.exceptions import ChaoxingQuizStateError

ASSIGNMENT_PATH = "/mooc-ans/mooc2/work/dowork"
ASSIGNMENT_RESULT_PATH = "/mooc-ans/mooc2/work/prompt"
ASSIGNMENT_SUBMIT_PATH = "/mooc-ans/work/addStudentWorkNewWeb"
ASSIGNMENT_QUESTION_SELECTOR = "#submitForm .questionLi"

ASSIGNMENT_STATE_SCRIPT = r"""() => {
    const host = location.hostname.toLowerCase();
    const trusted = host === 'chaoxing.com' || host.endsWith('.chaoxing.com');
    const route = location.pathname.toLowerCase().replace(/\/$/, '');
    const matched = window === window.top && trusted && (
        route === '/mooc-ans/mooc2/work/dowork' || route === '/mooc-ans/mooc2/work/prompt');
    if (!matched) return {assignment_page: false};
    const forms = document.querySelectorAll('#submitForm');
    const questions = document.querySelectorAll('#submitForm .questionLi');
    const declared = document.querySelector('#submitForm [name="totalQuestionNum"]')?.value;
    // 学习通的部分独立作业会将 totalQuestionNum 编码，不能将它直接作为数值解析。
    // 明文数量仍用于阻止只加载了部分题目的页面进入作答。
    const expected = declared !== undefined && /^\d+$/.test(declared.trim())
        ? Number(declared) : questions.length;
    const loaded = document.readyState === 'interactive' || document.readyState === 'complete';
    const visible = element => element.getClientRects().length > 0
        && getComputedStyle(element).visibility !== 'hidden';
    const successLabels = ['提交成功', '作业已提交', 'submitted successfully', 'submission successful'];
    const success = [...document.querySelectorAll(
        '[role="status"], .toast, #popcontent, .submitSuccess, .workStatus'
    )].some(element => visible(element) && successLabels.includes(
        (element.textContent || '').trim().toLowerCase().replace(/[！!。.]+$/, '')));
    const resultSuccess = route === '/mooc-ans/mooc2/work/prompt' && loaded
        && (document.body?.innerText || '').split('\n').some(line => successLabels.includes(
            line.trim().toLowerCase().replace(/[！!。.]+$/, '')));
    let submitPath = '';
    if (forms.length === 1) {
        const action = new URL(forms[0].action, location.href);
        if (action.origin === location.origin && forms[0].method.toLowerCase() === 'post') {
            submitPath = action.pathname;
        }
    }
    return {
        assignment_page: true,
        ready: loaded && forms.length === 1 && questions.length > 0
            && Number.isInteger(expected) && expected === questions.length,
        submitted: success || resultSuccess,
        question_count: questions.length,
        submit_path: submitPath,
        submit_fields: Object.fromEntries(['courseId', 'classId', 'workRelationId'].map(name => [
            name, forms.length === 1 ? forms[0].querySelector(`input[name="${name}"]`)?.value || '' : ''
        ])),
    };
}"""


def assignment_identity(url: str) -> tuple[str, str, str, str] | None:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme not in {"http", "https"}
        or not (host == "chaoxing.com" or host.endswith(".chaoxing.com"))
        or parsed.path.lower().rstrip("/") not in {ASSIGNMENT_PATH, ASSIGNMENT_RESULT_PATH}
    ):
        return None
    query: dict[str, list[str]] = {}
    for key, value in parse_qs(parsed.query).items():
        if key.lower() in query:
            return None
        query[key.lower()] = value
    values = [query.get(key, []) for key in ("courseid", "classid", "workid")]
    if any(len(value) != 1 or not value[0] for value in values):
        return None
    return host, values[0][0], values[1][0], values[2][0]


@dataclass(frozen=True, slots=True)
class AssignmentPageState:
    url: str = field(repr=False)
    ready: bool
    submitted: bool
    question_count: int
    submit_path: str
    submit_fields: dict[str, str] = field(repr=False)


def inspect_assignment_page(browser: Browser) -> AssignmentPageState:
    url = browser.current_url()
    if assignment_identity(url) is None:
        raise ChaoxingQuizStateError("Current page is not a supported standalone assignment.")
    matches = [
        result
        for result in browser.evaluate_in_frames(ASSIGNMENT_STATE_SCRIPT)
        if isinstance(result, dict) and result.get("assignment_page") is True
    ]
    if len(matches) != 1:
        raise ChaoxingQuizStateError("Standalone assignment page is missing or ambiguous.")
    raw = matches[0]
    if (
        type(raw.get("ready")) is not bool
        or type(raw.get("submitted")) is not bool
        or type(raw.get("question_count")) is not int
        or raw["question_count"] < 0
        or not isinstance(raw.get("submit_path"), str)
        or not isinstance(raw.get("submit_fields"), dict)
        or set(raw["submit_fields"]) != {"courseId", "classId", "workRelationId"}
        or any(not isinstance(value, str) for value in raw["submit_fields"].values())
    ):
        raise ChaoxingQuizStateError("Standalone assignment state is malformed.")
    if browser.current_url() != url:
        raise ChaoxingQuizStateError("Standalone assignment changed during inspection.")
    return AssignmentPageState(
        url, raw["ready"], raw["submitted"], raw["question_count"], raw["submit_path"], raw["submit_fields"]
    )
