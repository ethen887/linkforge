"""Real local Chromium DOM/capture tests; no Chaoxing network or model calls."""

from html import escape
from types import SimpleNamespace
from urllib.parse import quote

import pytest

from linkforge.browser.exceptions import BrowserError
from linkforge.browser.playwright import PlaywrightBrowser
from linkforge.platforms.chaoxing.exceptions import ChaoxingQuizStateError
from linkforge.platforms.chaoxing.quiz_dom import QUESTION_FRAME_PATH, QUESTION_SELECTOR
from linkforge.platforms.chaoxing.quiz_handler import ChaoxingQuizHandlerConfig, ChaoxingQuizTaskHandler
from linkforge.platforms.chaoxing.quiz_models import QuizAnswer, QuizQuestionType


def data_url(html, route):
    return f"data:text/html;charset=utf-8,{quote(html, safe='')}#{route}"


def fixture_page(*, inert=False, duplicate=False, marker_contract=False, unknown_heading=False):
    # Mirrors the observed role=radio + initially absent aria-checked contract.
    # Native inputs nested in checkbox role wrappers exercise de-duplication.
    html = """
    <style>.TiMu {padding: 16px; margin-bottom: 30px; width: 500px} li {padding: 8px}</style>
    <div class="TiMu newTiMu">
      <div class="Zy_TItle">1. (单选题, 20分) 题干：选择 B</div>
      <ul><li role="radio">A. 甲</li><li role="radio">B. 乙</li>
          <li role="radio">C. 丙</li><li role="radio">D. 丁</li></ul>
      <input type="hidden" id="answer1" value="">
    </div>
    <div class="TiMu newTiMu">
      <div class="Zy_TItle">2. (多选题) 选择 A 和 C</div>
      <ul><li role="checkbox" aria-checked="true"><input type="checkbox" checked>A. 甲</li>
          <li role="checkbox" aria-checked="true"><input type="checkbox" checked>B. 乙</li>
          <li role="checkbox" aria-checked="false"><input type="checkbox">C. 丙</li></ul>
      <input type="hidden" id="answer2" value="unknown-multi-encoding">
    </div>
    <div class="TiMu newTiMu">
      <div class="Zy_TItle">3. (判断题) 这是一道判断题</div>
      <ul><li role="radio" aria-checked="false">A. 对</li>
          <li role="radio" aria-checked="true">B. 错</li></ul>
      <input type="hidden" id="answer3" value="false">
    </div>
    <script>
    window.clicks = [];
    document.querySelectorAll('.TiMu').forEach((q, qi) => {
      const opts = Array.from(q.querySelectorAll('li'));
      if (MARKERS) opts.forEach((opt, i) => {
        opt.removeAttribute('aria-checked');
        opt.querySelector('input')?.remove();
        const marker = document.createElement('span');
        marker.className = qi === 1 ? 'num_option_dx' : 'num_option';
        marker.setAttribute('data', qi === 2 ? (i === 0 ? 'true' : 'false') : String.fromCharCode(65+i));
        opt.prepend(marker);
        q.querySelector('input[type=hidden]').value = '';
      });
      opts.forEach((opt, i) => opt.addEventListener('click', () => {
        window.clicks.push([qi, i]);
        if (INERT) return;
        if (MARKERS) {
          const multiple = opt.getAttribute('role') === 'checkbox';
          const cls = multiple ? 'check_answer_dx' : 'check_answer';
          const marker = opt.querySelector('span');
          const selected = !marker.classList.contains(cls);
          if (!multiple) opts.forEach(x => {
            x.querySelector('span').classList.remove(cls);
            x.setAttribute('aria-checked', 'false');
          });
          marker.classList.toggle(cls, selected);
          opt.setAttribute('aria-checked', String(selected));
          q.querySelector('input[type=hidden]').value = opts.map(x => x.querySelector('span'))
            .filter(x => x.classList.contains(cls)).map(x => x.getAttribute('data')).join('');
          return;
        }
        if (opt.getAttribute('role') === 'radio') {
          opts.forEach(x => x.setAttribute('aria-checked', String(x === opt)));
          q.querySelector('input[type=hidden]').value = String.fromCharCode(65 + i);
        } else {
          const selected = opt.getAttribute('aria-checked') !== 'true';
          opt.setAttribute('aria-checked', String(selected));
          opt.querySelector('input').checked = selected;
        }
      }));
    });
    </script>
    """.replace("INERT", "true" if inert else "false").replace(
        "MARKERS", "true" if marker_contract else "false"
    )
    if unknown_heading:
        html = html.replace("3. (判断题)", "3. (unreadable)")
    question_url = data_url(html, QUESTION_FRAME_PATH)
    work_html = (
        f'<iframe style="width:800px;height:1200px" src="{escape(question_url, quote=True)}"></iframe>'
    )
    if duplicate:
        work_html += work_html
    module_url = data_url(work_html, "/ananas/modules/work/index.html?id=1")
    cards = f'''<div class="ans-attach-ct"><span class="ans-job-icon"></span>
      <iframe style="width:900px;height:1500px" src="{escape(module_url, quote=True)}"></iframe></div>'''
    cards_url = data_url(cards, "/mooc-ans/knowledge/cards?knowledgeid=1")
    page = f'''<ul id="prev_tab"><li class="active">Quiz</li></ul>
      <iframe style="width:1000px;height:1800px" src="{escape(cards_url, quote=True)}"></iframe>'''
    return data_url(page, "/mycourse/studentstudy"), module_url


def test_real_nested_frames_capture_select_and_repeat_without_toggle():
    url, module_url = fixture_page()
    seen = []
    answers = [
        QuizAnswer(QuizQuestionType.SINGLE_CHOICE, ("B",)),
        QuizAnswer(QuizQuestionType.MULTIPLE_CHOICE, ("A", "C")),
        QuizAnswer(QuizQuestionType.TRUE_FALSE, ("B",)),
    ]

    def solve(question):
        assert question.image.data.startswith(b"\x89PNG\r\n\x1a\n")
        seen.append(question.index)
        return answers[question.index]

    with PlaywrightBrowser(headless=True, timeout_ms=3_000) as browser:
        browser.open(url)
        handler = ChaoxingQuizTaskHandler(browser, solver=SimpleNamespace(solve=solve))
        assert handler.answer_all() == tuple(answers)
        assert handler.answer_all() == tuple(answers)
        assert seen == [0, 1, 2, 0, 1, 2]
        assert [[0, 1], [1, 1], [1, 2]] in browser.evaluate_in_frames("() => window.clicks || null")
        with browser.element_scope(
            QUESTION_FRAME_PATH, QUESTION_SELECTOR, ancestor_url=module_url
        ) as elements:
            held = elements[0]
        with pytest.raises(BrowserError, match="closed"):
            held.screenshot()


@pytest.mark.parametrize("failure", ["inert", "duplicate"])
def test_real_dom_rejects_inert_click_and_ambiguous_frame(failure):
    url, _ = fixture_page(inert=failure == "inert", duplicate=failure == "duplicate")
    with PlaywrightBrowser(headless=True, timeout_ms=3_000) as browser:
        browser.open(url)
        handler = ChaoxingQuizTaskHandler(
            browser,
            solver=SimpleNamespace(solve=lambda q: QuizAnswer(QuizQuestionType.SINGLE_CHOICE, ("B",))),
            config=ChaoxingQuizHandlerConfig(readiness_timeout_seconds=0.2, selection_timeout_seconds=0.2),
        )
        with pytest.raises(ChaoxingQuizStateError):
            handler.answer_all()


def test_scope_does_not_retarget_replaced_question():
    url, module_url = fixture_page()
    with PlaywrightBrowser(headless=True, timeout_ms=3_000) as browser:
        browser.open(url)
        with browser.element_scope(
            QUESTION_FRAME_PATH, QUESTION_SELECTOR, ancestor_url=module_url
        ) as elements:
            elements[0].evaluate("e => e.replaceWith(e.cloneNode(true))")
            with pytest.raises(BrowserError, match="detached"):
                elements[0].screenshot()


@pytest.mark.parametrize("unknown_heading", [False, True])
def test_real_marker_contract_handles_uninitialized_multi_and_boolean_answers(unknown_heading):
    url, _ = fixture_page(marker_contract=True, unknown_heading=unknown_heading)
    answers = (
        QuizAnswer(QuizQuestionType.SINGLE_CHOICE, ("B",)),
        QuizAnswer(QuizQuestionType.MULTIPLE_CHOICE, ("A", "C")),
        QuizAnswer(QuizQuestionType.TRUE_FALSE, ("B",)),
    )
    with PlaywrightBrowser(headless=True, timeout_ms=3_000) as browser:
        browser.open(url)
        handler = ChaoxingQuizTaskHandler(browser, solver=SimpleNamespace(solve=lambda q: answers[q.index]))
        assert handler.answer_all() == answers
        assert handler.answer_all() == answers
        assert [[0, 1], [1, 0], [1, 2], [2, 1]] in browser.evaluate_in_frames("() => window.clicks || null")
