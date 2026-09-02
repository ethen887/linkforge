"""No-network integration test for the browser-agent loop."""

from urllib.parse import quote

from linkforge.action.browser import BrowserActionExecutor
from linkforge.action.models import ClickAction, FillAction
from linkforge.agent.browser import BrowserAgent
from linkforge.agent.loop import BrowserAgentLoop
from linkforge.agent.models import BrowserDecision, FinishDecision
from linkforge.browser.playwright import PlaywrightBrowser
from linkforge.observation.browser import BrowserObserver
from linkforge.observation.models import Observation


class FormAgent(BrowserAgent):
    """Deterministically complete the local form from each current observation."""

    def __init__(self) -> None:
        self.observations: list[Observation] = []
        self.selected_target_ids: list[int] = []

    def decide(self, observation: Observation) -> BrowserDecision:
        self.observations.append(observation)

        if "Completed" in observation.text:
            return FinishDecision()

        if "Name: LinkForge" in observation.text:
            target = next(
                element
                for element in observation.interactive_elements
                if element.role == "button" and element.name == "Submit"
            )
            self.selected_target_ids.append(target.target_id)
            return ClickAction(target_id=target.target_id)

        target = next(
            element
            for element in observation.interactive_elements
            if element.role == "textbox" and element.name == "Name"
        )
        self.selected_target_ids.append(target.target_id)
        return FillAction(target_id=target.target_id, text="LinkForge")


def test_browser_agent_loop_completes_local_form() -> None:
    html = """
    <!DOCTYPE html>
    <html>
        <head>
            <title>Browser Agent Loop Test</title>
        </head>
        <body>
            <label for="name">Name</label>
            <input
                id="name"
                type="text"
                oninput="document.getElementById('status').innerText = 'Name: ' + this.value;"
            >
            <button
                onclick="document.getElementById('status').innerText = 'Completed';"
            >
                Submit
            </button>
            <p id="status"></p>
        </body>
    </html>
    """
    data_url = f"data:text/html;charset=utf-8,{quote(html)}"
    agent = FormAgent()

    with PlaywrightBrowser(headless=True, timeout_ms=3_000) as browser:
        browser.open(data_url)
        loop = BrowserAgentLoop(
            observer=BrowserObserver(browser),
            agent=agent,
            executor=BrowserActionExecutor(browser),
        )

        loop.run(max_steps=3)

        assert "Completed" in browser.text()

    assert len(agent.observations) == 3
    first_ids = {element.target_id for element in agent.observations[0].interactive_elements}
    second_ids = {element.target_id for element in agent.observations[1].interactive_elements}
    assert first_ids.isdisjoint(second_ids)
    assert agent.selected_target_ids[0] in first_ids
    assert agent.selected_target_ids[1] in second_ids
