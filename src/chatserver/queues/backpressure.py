""" Backpressure module for the chat server library """

from __future__ import annotations

from enum import StrEnum


class BackpressurePolicy(StrEnum):
    DISCONNECT = "disconnect"
    DROP_OLDEST = "drop_oldest"
    DROP_NEWEST = "drop_newest"
    REJECT_CHAT = "reject_chat"
