"""The user's brains as the agent and Telegram see them: list them, and put one first.

Used by the switch_brain tool (the agent changes brains when asked, or when a task needs one that
can see pictures) and by Telegram's /brain command. The change is saved and applies at once: the
router reads the order on every call, so even the rest of the current answer uses the new brain.
"""

from pocketagent.config import Config
from pocketagent.llm import brain_label
from pocketagent.media import sees_images


class BrainChoice:
    def __init__(self, config: Config, save):
        self.config, self.save = config, save

    def describe(self) -> list[str]:
        lines = []
        for number, brain in enumerate(self.config.brains(), 1):
            notes = ["on" if brain.enabled else "off"]
            if sees_images(brain):
                notes.append("sees pictures")
            lines.append(f"{number}. {brain_label(brain)} ({', '.join(notes)})")
        return lines

    def prefer_index(self, index: int) -> str | None:
        brains = self.config.brains()
        if not 0 <= index < len(brains):
            return None
        brain = brains.pop(index)
        brain.enabled, brain.auto = True, False      # chosen by hand: on, and kept by the free-model sync
        self.config.set_brains([brain] + brains)
        self.save()
        return brain_label(brain)

    def prefer(self, name: str) -> str | None:
        """Put first the brain whose name contains `name` (case does not matter)."""
        wanted = name.strip().lower()
        for index, brain in enumerate(self.config.brains()):
            if wanted and (wanted in brain_label(brain).lower() or wanted in brain.model.lower()):
                return self.prefer_index(index)
        return None
