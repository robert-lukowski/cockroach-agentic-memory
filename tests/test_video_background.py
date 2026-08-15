"""Focused tests for the ambient Streamlit background video."""

from pathlib import Path

from frontend import video_background


def test_background_asset_exists() -> None:
    assert isinstance(video_background.BACKGROUND_VIDEO_PATH, Path)
    assert video_background.BACKGROUND_VIDEO_PATH.name == "tlo-dashboard.mp4"
    assert video_background.BACKGROUND_VIDEO_PATH.exists()


def test_background_renderer_uses_native_streamlit_video(monkeypatch) -> None:
    video_calls: list[tuple[object, dict[str, object]]] = []
    html_calls: list[str] = []

    class Container:
        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb):
            return False

    monkeypatch.setattr(video_background.st, "container", lambda **_kwargs: Container())
    monkeypatch.setattr(
        video_background.st,
        "video",
        lambda data, **kwargs: video_calls.append((data, kwargs)),
    )
    monkeypatch.setattr(video_background.st, "html", html_calls.append)

    video_background.render_background_video()

    assert len(video_calls) == 1
    data, kwargs = video_calls[0]
    assert str(data).endswith("frontend/static/tlo-dashboard.mp4")
    assert kwargs == {
        "format": "video/mp4",
        "autoplay": True,
        "muted": True,
        "loop": True,
    }
    assert html_calls
    assert "st-key-aim_ambient_video" in html_calls[0]
