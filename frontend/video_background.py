"""Presentation-only background video layer for the Streamlit command center."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

BACKGROUND_VIDEO_PATH = Path(__file__).resolve().parent / "static" / "tlo-dashboard.mp4"


def render_background_video() -> None:
    """Render the local MP4 through Streamlit's native media pipeline and pin it behind the UI."""
    if not BACKGROUND_VIDEO_PATH.exists():
        return

    with st.container(key="aim_ambient_video"):
        st.video(
            str(BACKGROUND_VIDEO_PATH),
            format="video/mp4",
            autoplay=True,
            muted=True,
            loop=True,
        )

    st.html(
        """
        <style>
          /*
           * Use Streamlit's native video element instead of static-file serving.
           * MP4 isn't on Streamlit's static-serving allow-list and is otherwise
           * returned as text/plain with nosniff, which browsers correctly reject.
           */
          .st-key-aim_ambient_video {
            position: fixed !important;
            inset: 0 !important;
            z-index: 0 !important;
            width: 100vw !important;
            height: 100vh !important;
            margin: 0 !important;
            padding: 0 !important;
            overflow: hidden !important;
            pointer-events: none !important;
            user-select: none !important;
          }

          .st-key-aim_ambient_video [data-testid="stVideo"] {
            position: absolute !important;
            inset: 0 !important;
            width: 100vw !important;
            height: 100vh !important;
            margin: 0 !important;
            padding: 0 !important;
          }

          .st-key-aim_ambient_video [data-testid="stVideo"] > div {
            width: 100% !important;
            height: 100% !important;
          }

          .st-key-aim_ambient_video video {
            width: 100vw !important;
            height: 100vh !important;
            object-fit: cover !important;
            opacity: 0.14 !important;
            filter: brightness(0.46) saturate(0.62) contrast(1.08) !important;
            transform: scale(1.025);
            pointer-events: none !important;
          }

          .st-key-aim_ambient_video video::-webkit-media-controls {
            display: none !important;
          }

          [data-testid="stAppViewContainer"]::before {
            z-index: 1;
          }

          [data-testid="stMainBlockContainer"] {
            position: relative;
            z-index: 2;
          }

          /* Keep ambient motion on mobile too, but make it slightly quieter. */
          @media (max-width: 900px) {
            .st-key-aim_ambient_video video {
              opacity: 0.10 !important;
              transform: scale(1.05);
            }
          }

          @media (prefers-reduced-motion: reduce) {
            .st-key-aim_ambient_video {
              display: none !important;
            }
          }
        </style>
        """
    )
