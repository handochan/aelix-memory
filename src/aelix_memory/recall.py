"""Bounded transient recall blocks that preserve previously emitted prompt prefixes."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

from .context import render_context
from .models import Hit, Memory

Anchor = tuple[str, int]
Epoch = tuple[str, str | None, int]


@dataclass(frozen=True)
class RecallBlock:
    text: str
    memories: tuple[Memory, ...]


class RecallLedger:
    """Session RAM only: no user text, persistent transcript or provider settings."""

    def __init__(self, *, budget: int = 12288, block_budget: int = 4096, anchors: int = 64):
        if not 1024 <= block_budget <= budget <= 32768 or not 1 <= anchors <= 256:
            raise ValueError("Invalid recall context bounds.")
        self.budget, self.block_budget, self.limit = budget, block_budget, anchors
        self.epoch: Epoch | None = None
        self.seen: OrderedDict[Anchor, None] = OrderedDict()
        self.blocks: OrderedDict[Anchor, RecallBlock] = OrderedDict()

    @property
    def size(self) -> int:
        return sum(len(block.text.encode()) for block in self.blocks.values())

    def clear(self) -> None:
        self.epoch = None
        self.seen.clear()
        self.blocks.clear()

    def prepare(self, epoch: Epoch, visible: set[Anchor]) -> None:
        if self.epoch != epoch:
            self.clear()
            self.epoch = epoch
        for anchor in tuple(self.seen):
            if anchor not in visible:
                self.seen.pop(anchor, None)
                self.blocks.pop(anchor, None)

    def records(self) -> dict[str, Memory]:
        return {memory.id: memory for block in self.blocks.values() for memory in block.memories}

    def prune(self, current: dict[str, Memory]) -> None:
        # Never retain a preview of a deleted, expired or replaced source record.
        for anchor, block in tuple(self.blocks.items()):
            if any(current.get(memory.id) != memory for memory in block.memories):
                self.blocks.pop(anchor)
                self.seen.pop(anchor, None)

    def append(self, anchor: Anchor, hits: tuple[Hit, ...]) -> None:
        if anchor in self.seen:
            return
        # Evict before deduplication so a relevant source in the retiring block
        # can be selected again at the newest turn.
        while len(self.seen) >= self.limit:
            oldest, _ = self.seen.popitem(last=False)
            self.blocks.pop(oldest, None)
        candidates = hits
        while True:
            already = self.records()
            hits = tuple(hit for hit in candidates if hit.memory.id not in already)
            text = render_context(hits, budget=self.block_budget)
            if not self.blocks or self.size + len(text.encode()) <= self.budget:
                break
            self.blocks.popitem(last=False)
        if text:
            emitted = tuple(hit.memory for hit in hits if f'id="{hit.memory.id}"' in text)
            self.blocks[anchor] = RecallBlock(text, emitted)
        self.seen[anchor] = None

    def get(self, anchor: Anchor) -> str:
        block = self.blocks.get(anchor)
        return block.text if block else ""
