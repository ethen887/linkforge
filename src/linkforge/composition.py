"""LinkForge 各入口点共享的组装辅助函数。"""

from linkforge.application import ApplicationConfig, LinkForgeApplication
from linkforge.platforms.chaoxing.quiz_submitter import ChaoxingQuizSubmitter
from linkforge.platforms.chaoxing.runtime import ChaoxingPlatformRuntime


def create_application(config: ApplicationConfig) -> LinkForgeApplication:
    """为受支持的平台构建生产环境使用的 LinkForge 应用。"""
    platform = ChaoxingPlatformRuntime(
        quiz_submitter=ChaoxingQuizSubmitter(), on_course_url_changed=config.on_course_url_changed
    )
    return LinkForgeApplication(config=config, platform=platform)
