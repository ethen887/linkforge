"""Development entry point for the current LinkForge application runtime."""

from __future__ import annotations

import logging
import os

from linkforge.application import ApplicationConfig, LinkForgeApplication
from linkforge.config import BrowserConfig, create_model_config
from linkforge.log import setup_logging
from linkforge.platforms.chaoxing.quiz_submitter import ChaoxingQuizSubmitter
from linkforge.platforms.chaoxing.runtime import ChaoxingPlatformRuntime

_COURSE_URL_ENV = "LINKFORGE_COURSE_URL"
_PROVIDER_ENV = "LINKFORGE_PROVIDER"
_MODEL_ENV = "LINKFORGE_MODEL"
_API_KEY_ENV = "LINKFORGE_API_KEY"
_PROFILE_DIR_ENV = "LINKFORGE_PROFILE_DIR"

logger = logging.getLogger(__name__)


def _get_required_env(name: str) -> str:
    """Return one non-empty required environment variable."""
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value.strip()


def main() -> None:
    """Compose and run LinkForge against one Chaoxing course."""
    log_file = setup_logging()
    logger.info("Logging initialized: %s", log_file)
    try:
        course_url = _get_required_env(_COURSE_URL_ENV)
        provider = _get_required_env(_PROVIDER_ENV)
        model = _get_required_env(_MODEL_ENV)
        api_key = _get_required_env(_API_KEY_ENV)

        profile_dir = os.environ.get(_PROFILE_DIR_ENV)
        if profile_dir is not None:
            profile_dir = profile_dir.strip() or None

        model_config = create_model_config(
            provider=provider,
            api=api_key,
            model_name=model,
        )
        browser_config = BrowserConfig(
            headless=False,
            profile_dir=profile_dir,
        )
        config = ApplicationConfig(
            course_url=course_url,
            browser_config=browser_config,
            model_config=model_config,
        )
        platform = ChaoxingPlatformRuntime(
            quiz_submitter=ChaoxingQuizSubmitter(),
        )
        app = LinkForgeApplication(
            config=config,
            platform=platform,
        )

        print("LinkForge starting...")
        print(f"Course: {course_url}")
        print(f"Provider: {provider}")
        print(f"Model: {model}")

        logger.info("Application starting (provider=%s, model=%s)", provider, model)
        app.run()
    except BaseException:
        logger.exception("LinkForge terminated with an unhandled error")
        raise
    logger.info("LinkForge exited normally")


if __name__ == "__main__":
    main()
