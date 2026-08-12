# Plugins module for aldi-watcher
from .base_watcher import BaseWatcher
from .aldi_talk import AldiTalkWatcher
from .lidl_connect import LidlConnectWatcher

__all__ = ["BaseWatcher", "AldiTalkWatcher", "LidlConnectWatcher"]
