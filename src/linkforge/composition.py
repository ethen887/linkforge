"""Shared composition helpers for LinkForge entry points."""

from linkforge.application import ApplicationConfig, LinkForgeApplication
from linkforge.platforms.chaoxing.quiz_submitter import ChaoxingQuizSubmitter
from linkforge.platforms.chaoxing.runtime import ChaoxingPlatformRuntime


def create_application(config: ApplicationConfig) -> LinkForgeApplication:
    """Build the production LinkForge application for the supported platform."""
    platform = ChaoxingPlatformRuntime(quiz_submitter=ChaoxingQuizSubmitter())
    return LinkForgeApplication(config=config, platform=platform)
