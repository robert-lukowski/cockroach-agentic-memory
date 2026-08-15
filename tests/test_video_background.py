"""Focused tests for the ambient Streamlit background video."""

from pathlib import Path

from frontend import video_background


def test_background_asset_exists() -> None:
    assert isinstance(video_background.BACKGROUND_VIDEO_PATH, Path)
    assert video_background.BACKGROUND_VIDEO_PATH.name == "tlo-dashboard.mp4"
    assert video_background.BACKGROUND_VIDEO_PATH.exists()
