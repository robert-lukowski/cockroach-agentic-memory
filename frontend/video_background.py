"""Presentation-only background video layer for the Streamlit command center."""

from __future__ import annotations

import streamlit as st

BACKGROUND_VIDEO_URL = "/app/static/tlo-dashboard.mp4"


def render_background_video() -> None:
    """Render a low-opacity, non-interactive background video behind the UI."""
    st.html(
        f"""
        <div class="aim-video-layer" aria-hidden="true">
          <video autoplay muted loop playsinline preload="metadata" tabindex="-1">
            <source src="{BACKGROUND_VIDEO_URL}" type="video/mp4">
          </video>
        </div>
        <style>
          .aim-video-layer {{
            position: fixed;
            inset: 0;
            z-index: 0;
            overflow: hidden;
            pointer-events: none;
            user-select: none;
          }}

          .aim-video-layer video {{
            width: 100vw;
            height: 100vh;
            object-fit: cover;
            opacity: 0.12;
            filter: brightness(0.48) saturate(0.60) contrast(1.08);
            transform: scale(1.025);
          }}

          [data-testid="stAppViewContainer"]::before {{
            z-index: 1;
          }}

          [data-testid="stMainBlockContainer"] {{
            position: relative;
            z-index: 2;
          }}

          @media (max-width: 900px) {{
            .aim-video-layer {{
              display: none;
            }}
          }}

          @media (prefers-reduced-motion: reduce) {{
            .aim-video-layer {{
              display: none;
            }}
          }}
        </style>
        """
    )
