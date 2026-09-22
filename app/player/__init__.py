"""Playback engine layer.

``backend``    — the engine-agnostic contract (protocol, events, error types)
``mpv_backend``— the libmpv implementation of that contract
``mpv_surface``— the Qt/OpenGL video surface used by the libmpv backend
``controller`` — the Qt signal façade the UI talks to
"""
