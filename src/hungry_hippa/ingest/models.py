"""Provider-neutral shapes produced by the ingestion parsers.

Slice 1 defines the *shape* only. This module does not write to the memory
database and does not import the runtime's storage, policy or MCP layers: a
parser's job is to turn a provider export into an inspectable, deterministic
sequence of turns and then stop. Slice 2 persists these values as raw history
without mutating them.

Two ideas are deliberately separate:

``turns``
    every supported textual turn found in the export, including turns on
    abandoned or regenerated branches. Nothing is dropped for looking
    "historical": an edited prompt or a regenerated answer is evidence about how
    the conversation actually unfolded.

``current_path_turn_ids``
    the subset of those turns the provider considered *visible* at export time
    (the path from the root to ``current_node``). Alternate branches are still
    in ``turns``.

The dataclasses are frozen: a parse result is a snapshot, and downstream slices
should build new values rather than mutate these in place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

#: Role values this project knows how to talk about. A parser preserves whatever
#: the provider used, including roles outside this set.
KNOWN_ROLES = ("user", "assistant", "system", "tool")


@dataclass(frozen=True)
class NormalizedTurn:
    """One textual turn, with enough provenance to place it in the tree.

    ``turn_id`` and ``parent_turn_id`` are the provider's own ids, never
    generated: they are the only stable way to refer to a node again, and
    regenerating them would make an import impossible to reconcile later.

    ``branch_path`` is the lineage from the conversation root to this node,
    *including* structural nodes that carry no message. That is what lets a later
    slice rebuild "the answer the user kept" versus "the answer they regenerated
    away from" without re-reading the export.
    """

    source: str
    session_id: str
    session_title: Optional[str]
    turn_id: str
    parent_turn_id: Optional[str]
    role: str
    content: str
    occurred_at: Optional[float]
    branch_path: Tuple[str, ...] = ()
    source_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "session_id": self.session_id,
            "session_title": self.session_title,
            "turn_id": self.turn_id,
            "parent_turn_id": self.parent_turn_id,
            "role": self.role,
            "content": self.content,
            "occurred_at": self.occurred_at,
            "branch_path": list(self.branch_path),
            "source_metadata": dict(self.source_metadata),
        }


@dataclass(frozen=True)
class ParsedConversation:
    """One conversation: all supported turns plus the active branch.

    ``warnings`` records everything the parser refused to guess at (a node that
    was not an object, an unknown child id, a content type it cannot represent as
    text). A malformed node therefore degrades into a line of diagnostic text
    instead of losing the rest of the conversation.
    """

    source: str
    session_id: str
    title: Optional[str]
    turns: Tuple[NormalizedTurn, ...] = ()
    current_path_turn_ids: Tuple[str, ...] = ()
    #: every node on the active path, including structural nodes with no message
    current_path_node_ids: Tuple[str, ...] = ()
    current_node: Optional[str] = None
    created_at: Optional[float] = None
    updated_at: Optional[float] = None
    warnings: Tuple[str, ...] = ()
    source_metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def turn_ids(self) -> Tuple[str, ...]:
        return tuple(t.turn_id for t in self.turns)

    @property
    def turn_count(self) -> int:
        return len(self.turns)

    @property
    def current_path_turns(self) -> Tuple[NormalizedTurn, ...]:
        """Active-branch turns, in root-to-current order."""
        index = {turn_id: i for i, turn_id in enumerate(self.current_path_turn_ids)}
        return tuple(sorted((t for t in self.turns if t.turn_id in index),
                            key=lambda t: index[t.turn_id]))

    @property
    def alternate_branch_turns(self) -> Tuple[NormalizedTurn, ...]:
        """Turns that exist in the export but are not on the active branch."""
        active = set(self.current_path_turn_ids)
        return tuple(t for t in self.turns if t.turn_id not in active)

    def turn(self, turn_id: str) -> Optional[NormalizedTurn]:
        for t in self.turns:
            if t.turn_id == turn_id:
                return t
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "session_id": self.session_id,
            "title": self.title,
            "current_node": self.current_node,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "current_path_turn_ids": list(self.current_path_turn_ids),
            "current_path_node_ids": list(self.current_path_node_ids),
            "turn_count": self.turn_count,
            "turns": [t.to_dict() for t in self.turns],
            "warnings": list(self.warnings),
        }


def summarize(conversations: List[ParsedConversation]) -> Dict[str, int]:
    """Counts for a dry-run report. Pure; reads only what the parser produced."""
    turns = sum(c.turn_count for c in conversations)
    current = sum(len(c.current_path_turn_ids) for c in conversations)
    return {
        "conversations": len(conversations),
        "turns": turns,
        "current_path_turns": current,
        "alternate_branch_turns": turns - current,
        "warnings": sum(len(c.warnings) for c in conversations),
    }
