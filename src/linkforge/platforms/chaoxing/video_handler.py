"""任务点视频与普通学习通视频的确定性生命周期。"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from linkforge.application.task_runner import TaskHandler
from linkforge.browser.base import Browser
from linkforge.browser.exceptions import BrowserError
from linkforge.platforms.chaoxing.dom import FRAME_PATH_SCRIPT, inspect_chaoxing_page
from linkforge.platforms.chaoxing.exceptions import (
    ChaoxingInspectionError,
    VideoPlaybackError,
    VideoTaskError,
    VideoTimeoutError,
)
from linkforge.platforms.chaoxing.models import (
    ChaoxingModuleState,
    ChaoxingPageState,
    ChaoxingVideoState,
)
from linkforge.platforms.chaoxing.video_state import VideoSession

_VIDEO_MODULE_PATH = "/ananas/modules/video/"
_PROGRESS_EPSILON_SECONDS = 0.05

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ChaoxingVideoHandlerConfig:
    """确定性视频生命周期所使用的有界等待参数。"""

    poll_interval_seconds: float = 1.0
    overall_timeout_seconds: float = 8 * 60 * 60
    video_available_timeout_seconds: float = 30.0
    playback_start_timeout_seconds: float = 15.0
    progress_timeout_seconds: float = 90.0
    stall_recovery_interval_seconds: float = 15.0
    stall_recovery_attempts: int = 2
    platform_finished_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        for name, value in (
            ("poll_interval_seconds", self.poll_interval_seconds),
            ("overall_timeout_seconds", self.overall_timeout_seconds),
            ("video_available_timeout_seconds", self.video_available_timeout_seconds),
            ("playback_start_timeout_seconds", self.playback_start_timeout_seconds),
            ("progress_timeout_seconds", self.progress_timeout_seconds),
            ("stall_recovery_interval_seconds", self.stall_recovery_interval_seconds),
            ("platform_finished_timeout_seconds", self.platform_finished_timeout_seconds),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be greater than 0")
        if (
            not isinstance(self.stall_recovery_attempts, int)
            or isinstance(self.stall_recovery_attempts, bool)
            or self.stall_recovery_attempts < 0
        ):
            raise ValueError("stall_recovery_attempts must be a non-negative integer")


class ChaoxingVideoTaskHandler(TaskHandler):
    """播放视频，并验证平台或普通媒体的完成状态。"""

    def __init__(
        self,
        browser: Browser,
        *,
        config: ChaoxingVideoHandlerConfig | None = None,
        video_session: VideoSession | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._browser = browser
        self._config = config or ChaoxingVideoHandlerConfig()
        self._video_session = video_session or VideoSession()
        self._sleep = sleep
        self._monotonic = monotonic

    def run(self) -> None:
        """运行当前视频，直到观察到其适用的完成状态为止。"""
        self.run_interruptibly()

    def run_interruptibly(self, *, should_stop: Callable[[], bool] | None = None) -> None:
        """轮询视频时响应停止，并保留未完成的视频状态。"""
        logger.info("Video handler started")
        try:
            completed = self._run(should_stop=should_stop)
        except BaseException:
            logger.error("Video handler failed")
            raise
        if completed:
            logger.info("Video handler completed")
        else:
            logger.info("Video handler stopped")

    def _run(self, *, should_stop: Callable[[], bool] | None = None) -> bool:
        """驱动视频处理主循环，直到观察到平台或普通媒体的完成状态。"""
        if should_stop is not None and should_stop():
            return False
        initial_state = self._inspect()
        target = self._locate_target(initial_state)
        if target is None:
            return True
        logger.debug(
            "Video target selected: module_count=%d, same_url_count=%d, frame_path=%s",
            len(initial_state.modules),
            sum(module.url == target.url for module in initial_state.modules),
            target.frame_path,
        )
        requires_platform_completion = target.has_job_icon
        if not requires_platform_completion:
            logger.info("Video task marker absent; waiting for dynamic marker while observing playback")

        started_at = self._monotonic()
        last_progress_at = started_at
        last_current_time: float | None = None
        video_missing_since: float | None = None
        module_missing_since: float | None = None
        inspection_failed_since: float | None = None
        media_ended_since: float | None = None
        play_attempted = False
        play_requested_at: float | None = None
        recovery_attempts = 0
        last_recovery_at = started_at

        while True:
            if should_stop is not None and should_stop():
                return False
            now = self._monotonic()
            if now - started_at >= self._config.overall_timeout_seconds:
                raise VideoTimeoutError(
                    "Timed out before Chaoxing confirmed the video task point as finished."
                )

            try:
                state = inspect_chaoxing_page(self._browser)
            except ChaoxingInspectionError as exc:
                if inspection_failed_since is None:
                    inspection_failed_since = now
                if now - inspection_failed_since >= self._config.video_available_timeout_seconds:
                    raise VideoTaskError(
                        "Chaoxing frame inspection did not recover before the availability deadline."
                    ) from exc
                self._sleep(self._config.poll_interval_seconds)
                continue

            inspection_failed_since = None
            if should_stop is not None and should_stop():
                return False
            if (
                state.content_frame_url != initial_state.content_frame_url
                or state.active_tab_index != initial_state.active_tab_index
            ):
                raise VideoTaskError("The Chaoxing card changed before video completion could be verified.")
            current_module = self._find_module(state, target)
            if current_module is not None and current_module.has_job_icon:
                requires_platform_completion = True
            if current_module is not None and current_module.has_job_icon and current_module.finished:
                return True
            if current_module is None:
                if module_missing_since is None:
                    module_missing_since = now
                if (
                    media_ended_since is None or not requires_platform_completion
                ) and now - module_missing_since >= self._config.video_available_timeout_seconds:
                    raise VideoTimeoutError(
                        "The target Chaoxing task-point module disappeared before completion."
                    )
            else:
                module_missing_since = None

            video = self._find_video(state, target)
            if video is None:
                play_attempted = False
                play_requested_at = None
                if video_missing_since is None:
                    video_missing_since = now
                missing_timeout = (
                    self._config.platform_finished_timeout_seconds
                    if media_ended_since is not None
                    else self._config.video_available_timeout_seconds
                )
                if now - video_missing_since >= missing_timeout:
                    if media_ended_since is not None:
                        raise VideoTimeoutError(
                            "The media ended, but Chaoxing did not confirm the task point as finished."
                        )
                    raise VideoTimeoutError(
                        "The target Chaoxing video frame or HTML video element did not become available."
                    )
                self._sleep(self._config.poll_interval_seconds)
                continue

            video_missing_since = None

            if video.ended:
                if media_ended_since is None:
                    media_ended_since = now
                if not requires_platform_completion:
                    if (
                        current_module is not None
                        and now - started_at >= self._config.video_available_timeout_seconds
                    ):
                        module_index = state.modules.index(current_module)
                        self._video_session.mark_handled(state, module_index)
                        logger.info(
                            "Ordinary video completed after real media ending and marker readiness wait"
                        )
                        return True
                elif now - media_ended_since >= self._config.platform_finished_timeout_seconds:
                    raise VideoTimeoutError(
                        "The media ended, but Chaoxing did not confirm the task point as finished."
                    )
            else:
                media_ended_since = None
                if video.paused and not play_attempted:
                    self._request_play(target)
                    play_attempted = True
                    play_requested_at = now
                    last_progress_at = now
                elif (
                    video.paused
                    and play_requested_at is not None
                    and now - play_requested_at >= self._config.playback_start_timeout_seconds
                ):
                    raise VideoPlaybackError(
                        "The Chaoxing video remained paused after playback was requested."
                    )
                elif not video.paused:
                    # 仅在观察到真实播放后重新武装，这样后续的暂停才能再次被恢复。
                    play_attempted = False
                    play_requested_at = None

                if (
                    last_current_time is None
                    or video.current_time > last_current_time + _PROGRESS_EPSILON_SECONDS
                ):
                    last_current_time = video.current_time
                    last_progress_at = now
                    recovery_attempts = 0
                    last_recovery_at = now
                elif now - last_progress_at >= self._config.progress_timeout_seconds:
                    self._log_stalled_video(video, target, recovery_attempts, now - last_progress_at)
                    raise VideoTimeoutError(
                        "The Chaoxing video made no playback progress before the progress deadline."
                    )
                else:
                    # 播放器可能在媒体时钟停滞时报告 paused=False。
                    # 在不出于 seek、不重新加载、不延长进度截止时间、也不改变任务完成
                    # 状态的前提下，重试正常的播放控制。
                    if (
                        not video.paused
                        and recovery_attempts < self._config.stall_recovery_attempts
                        and now - last_recovery_at >= self._config.stall_recovery_interval_seconds
                    ):
                        recovery_attempts += 1
                        last_recovery_at = now
                        self._log_stalled_video(video, target, recovery_attempts, now - last_progress_at)
                        self._request_play(target, restart=True)
                        logger.info("Video stall recovery requested")
                    # 平台可能恢复到更早的媒体位置。将其作为下一个基线；
                    # 向后跳转本身并不算进度。
                    if video.current_time < last_current_time - _PROGRESS_EPSILON_SECONDS:
                        last_current_time = video.current_time

            self._sleep(self._config.poll_interval_seconds)

    def _inspect(self) -> ChaoxingPageState:
        try:
            return inspect_chaoxing_page(self._browser)
        except ChaoxingInspectionError as exc:
            raise VideoTaskError("Unable to inspect the current Chaoxing video task.") from exc

    def _locate_target(self, state: ChaoxingPageState) -> ChaoxingModuleState | None:
        """在当前卡片中定位待处理的视频目标模块；没有则返回 None 或抛错。"""
        pending = next(
            (
                module
                for index, module in enumerate(state.modules)
                if not (module.has_job_icon and module.finished)
                and not self._video_session.is_handled(state, index)
                and not self._video_session.is_deferred(state, index)
            ),
            None,
        )
        if pending is not None and _VIDEO_MODULE_PATH in pending.url:
            return pending

        finished_videos = [
            module
            for module in state.modules
            if _VIDEO_MODULE_PATH in module.url and module.has_job_icon and module.finished
        ]
        if finished_videos or any(
            _VIDEO_MODULE_PATH in module.url
            and (
                self._video_session.is_handled(state, index)
                or self._video_session.is_deferred(state, index)
            )
            for index, module in enumerate(state.modules)
        ):
            # 检测器与处理器是两次独立的观察；两者之间的完成是良性的。
            return None

        if pending is None:
            raise VideoTaskError("No Chaoxing video task point exists in the current card.")
        raise VideoTaskError("The first pending Chaoxing module is no longer the detected video.")

    @staticmethod
    def _find_module(state: ChaoxingPageState, target: ChaoxingModuleState) -> ChaoxingModuleState | None:
        matches = [
            module
            for module in state.modules
            if module.url == target.url
            and (target.frame_path is None or module.frame_path == target.frame_path)
        ]
        if len(matches) > 1:
            raise VideoTaskError("The target Chaoxing video module is ambiguous.")
        return matches[0] if matches else None

    @staticmethod
    def _find_video(state: ChaoxingPageState, target: ChaoxingModuleState) -> ChaoxingVideoState | None:
        matches = [
            video
            for video in state.videos
            if video.frame_url == target.url
            and (target.frame_path is None or video.frame_path == target.frame_path)
        ]
        if len(matches) > 1:
            raise VideoTaskError("The target Chaoxing video frame is ambiguous.")
        return matches[0] if matches else None

    @staticmethod
    def _log_stalled_video(
        video: ChaoxingVideoState,
        target: ChaoxingModuleState,
        recovery_attempts: int,
        stalled_seconds: float,
    ) -> None:
        logger.warning(
            "Video playback stalled: paused=%s ended=%s current_time=%.3f duration=%s "
            "ready_state=%d frame_path=%s recovery_attempts=%d stalled_seconds=%.1f",
            video.paused,
            video.ended,
            video.current_time,
            video.duration,
            video.ready_state,
            target.frame_path,
            recovery_attempts,
            stalled_seconds,
        )

    def _request_play(self, target: ChaoxingModuleState, *, restart: bool = False) -> None:
        """在目标视频 frame 中请求播放；restart=True 时先暂停再重播。"""
        expression = _play_video_script(target.url, target.frame_path, restart=restart)
        try:
            results = self._browser.evaluate_in_frames(expression)
        except BrowserError as exc:
            raise VideoPlaybackError("Failed to request playback in Chaoxing video frames.") from exc

        matching_results = [
            result for result in results if isinstance(result, dict) and result.get("matched") is True
        ]
        if len(matching_results) != 1:
            raise VideoPlaybackError("The target Chaoxing video frame detached or became ambiguous.")

        result = matching_results[0]
        error = result.get("error")
        paused = result.get("paused")
        ended = result.get("ended")
        video_count = result.get("video_count")
        if error is not None:
            if not isinstance(error, str):
                raise VideoPlaybackError("The Chaoxing playback result was malformed.")
            raise VideoPlaybackError(f"Chaoxing video playback was rejected: {error}")
        if video_count != 1 or not isinstance(paused, bool) or not isinstance(ended, bool):
            raise VideoPlaybackError("The Chaoxing playback result was malformed.")


def _play_video_script(
    target_url: str, target_path: tuple[int, ...] | None = None, *, restart: bool = False
) -> str:
    serialized_url = json.dumps(target_url)
    serialized_path = json.dumps(target_path)
    serialized_restart = json.dumps(restart)
    return f"""() => {{
        {FRAME_PATH_SCRIPT}
        const frameUrl = window.location.href;
        const targetPath = {serialized_path};
        if (frameUrl !== {serialized_url}
            || (targetPath !== null && JSON.stringify(framePath) !== JSON.stringify(targetPath))) {{
            return {{frame_url: frameUrl, matched: false}};
        }}

        const videos = document.querySelectorAll("video");
        if (videos.length !== 1) {{
            return {{
                frame_url: frameUrl,
                matched: true,
                video_count: videos.length,
                paused: true,
                ended: false,
                error: null,
            }};
        }}

        const video = videos[0];
        let error = null;
        if ({serialized_restart} && !video.ended) {{
            video.pause();
        }}
        if (video.paused && !video.ended) {{
            try {{
                const playRequest = video.play();
                if (playRequest && typeof playRequest.catch === "function") {{
                    playRequest.catch(() => {{}});
                }}
            }} catch (reason) {{
                error = reason instanceof Error
                    ? `${{reason.name}}: ${{reason.message}}`
                    : String(reason);
            }}
        }}

        return {{
            frame_url: frameUrl,
            matched: true,
            video_count: videos.length,
            paused: video.paused,
            ended: video.ended,
            error,
        }};
    }}"""
