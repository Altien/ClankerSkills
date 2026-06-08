"""Curated flow diagrams: server-rendered clickable SVG.

curated/diagrams.yaml follows the explorer's discipline: every node
anchors to a real doc heading or code symbol and carries a hand-written
one-line summary — the verifier and the drift page police dangling
anchors. Clicking a node swaps the adjacent panel to the anchored
content via htmx.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path

import yaml

from .config import ConfigError
from .journeys import Stop, resolve_stop

NODE_TYPES = ("start", "step", "decision", "output", "stop")

# geometry
_W, _BOX_W, _BOX_H, _GAP, _PAD = 560, 420, 56, 34, 20


@dataclass(frozen=True)
class Node:
    id: str
    type: str
    label: str
    summary: str
    doc: str | None = None
    heading: str | None = None
    path: str | None = None
    symbol: str | None = None
    loop_to: str | None = None
    when: str = ""

    def as_stop(self) -> Stop:
        return Stop(
            narration="-", doc=self.doc, heading=self.heading, path=self.path, symbol=self.symbol
        )


@dataclass(frozen=True)
class Diagram:
    id: str
    title: str
    doc: str            # the corpus doc this diagram attaches to
    nodes: tuple[Node, ...]

    def node(self, node_id: str) -> Node | None:
        return next((n for n in self.nodes if n.id == node_id), None)


@dataclass(frozen=True)
class DanglingNode:
    diagram_id: str
    node_id: str
    label: str
    reason: str


def load_diagrams(path: Path) -> list[Diagram]:
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    diagrams: list[Diagram] = []
    seen: set[str] = set()
    for i, raw in enumerate(data):
        diagram_id = raw.get("id", "")
        if not diagram_id or diagram_id in seen:
            raise ConfigError(f"diagrams[{i}] needs a unique id")
        seen.add(diagram_id)
        for key in ("title", "doc"):
            if not str(raw.get(key, "")).strip():
                raise ConfigError(f"diagram '{diagram_id}' missing '{key}'")
        nodes_raw = raw.get("nodes") or []
        if len(nodes_raw) < 2:
            raise ConfigError(f"diagram '{diagram_id}' needs at least 2 nodes")
        nodes: list[Node] = []
        node_ids: set[str] = set()
        for j, node in enumerate(nodes_raw):
            node_id = node.get("id", "")
            if not node_id or node_id in node_ids:
                raise ConfigError(f"diagram '{diagram_id}' node {j + 1} needs a unique id")
            node_ids.add(node_id)
            node_type = node.get("type", "step")
            if node_type not in NODE_TYPES:
                raise ConfigError(
                    f"diagram '{diagram_id}' node '{node_id}' type '{node_type}' "
                    f"not in {NODE_TYPES}"
                )
            if not str(node.get("label", "")).strip():
                raise ConfigError(f"diagram '{diagram_id}' node '{node_id}' missing label")
            if not str(node.get("summary", "")).strip():
                raise ConfigError(
                    f"diagram '{diagram_id}' node '{node_id}' missing its one-line summary"
                )
            has_doc = bool(node.get("doc"))
            has_path = bool(node.get("path"))
            if has_doc == has_path:
                raise ConfigError(
                    f"diagram '{diagram_id}' node '{node_id}' must anchor to "
                    "exactly one of doc/path"
                )
            nodes.append(
                Node(
                    id=node_id,
                    type=node_type,
                    label=str(node["label"]).strip(),
                    summary=str(node["summary"]).strip(),
                    doc=node.get("doc"),
                    heading=node.get("heading"),
                    path=node.get("path"),
                    symbol=node.get("symbol"),
                    loop_to=node.get("loop_to"),
                    when=str(node.get("when", "")).strip(),
                )
            )
        for node in nodes:
            if node.loop_to and node.loop_to not in node_ids:
                raise ConfigError(
                    f"diagram '{diagram_id}' node '{node.id}' loop_to "
                    f"unknown node '{node.loop_to}'"
                )
        diagrams.append(
            Diagram(id=diagram_id, title=str(raw["title"]).strip(), doc=raw["doc"], nodes=tuple(nodes))
        )
    return diagrams


def find_dangling_nodes(diagrams: list[Diagram], registry) -> list[DanglingNode]:
    dangling: list[DanglingNode] = []
    for diagram in diagrams:
        for node in diagram.nodes:
            reason = resolve_stop(node.as_stop(), registry)
            if reason is not None:
                dangling.append(DanglingNode(diagram.id, node.id, node.label, reason))
    return dangling


def render_svg(diagram: Diagram) -> str:
    """Vertical flow: rounded boxes, arrows, dashed loop edges, htmx clicks."""
    total_h = _PAD * 2 + len(diagram.nodes) * _BOX_H + (len(diagram.nodes) - 1) * _GAP
    box_x = (_W - _BOX_W - 80) // 2  # leave room on the right for loop edges
    cx = box_x + _BOX_W // 2
    positions = {
        node.id: _PAD + i * (_BOX_H + _GAP) for i, node in enumerate(diagram.nodes)
    }

    parts: list[str] = [
        f'<svg class="flow-diagram" viewBox="0 0 {_W} {total_h}" '
        f'role="img" aria-label="{html.escape(diagram.title)}">',
        '<defs><marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" '
        'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        '<path d="M0,0 L8,4 L0,8 z" class="d-arrowhead"/></marker></defs>',
    ]

    # edges between consecutive nodes
    for prev, nxt in zip(diagram.nodes, diagram.nodes[1:]):
        y1 = positions[prev.id] + _BOX_H
        y2 = positions[nxt.id]
        parts.append(
            f'<line class="d-edge" x1="{cx}" y1="{y1}" x2="{cx}" y2="{y2 - 2}" '
            'marker-end="url(#arrow)"/>'
        )

    # loop edges
    for node in diagram.nodes:
        if not node.loop_to:
            continue
        y_from = positions[node.id] + _BOX_H // 2
        y_to = positions[node.loop_to] + _BOX_H // 2
        x_edge = box_x + _BOX_W
        x_out = x_edge + 52
        parts.append(
            f'<path class="d-loop" d="M {x_edge} {y_from} C {x_out} {y_from}, '
            f'{x_out} {y_to}, {x_edge + 4} {y_to}" marker-end="url(#arrow)"/>'
        )
        if node.when:
            mid_y = (y_from + y_to) // 2
            parts.append(
                f'<text class="d-when" x="{x_out + 2}" y="{mid_y}" '
                f'text-anchor="start">{html.escape(node.when)}</text>'
            )

    # nodes (after edges so boxes sit on top)
    for node in diagram.nodes:
        y = positions[node.id]
        parts.append(
            f'<g class="d-node d-{node.type}" tabindex="0" role="button" '
            f'hx-get="/partial/diagram-node?diagram={diagram.id}&amp;node={node.id}" '
            f'hx-target="#diagram-panel-{diagram.id}" hx-swap="innerHTML">'
            f'<rect x="{box_x}" y="{y}" rx="10" width="{_BOX_W}" height="{_BOX_H}"/>'
            f'<text class="d-label" x="{cx}" y="{y + _BOX_H // 2 - 4}" '
            f'text-anchor="middle">{html.escape(node.label)}</text>'
            f'<text class="d-type" x="{cx}" y="{y + _BOX_H // 2 + 16}" '
            f'text-anchor="middle">{node.type}</text>'
            "</g>"
        )

    parts.append("</svg>")
    return "".join(parts)
