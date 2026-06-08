"""The Atlas — documentation navigator server.

Run from this directory:
    uvicorn app:app --reload --port 8400

All repo-specific wiring lives in atlas.config.yaml (see DESIGN.md §6).
"""

from __future__ import annotations

from pathlib import Path

import html as html_mod
import mimetypes

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from engine.code_panel import PanelError, pygments_css, render_file, safe_resolve
from engine.comments import COMMENT_TYPES, STATUSES, CommentStore, mark_orphans
from engine.diagrams import render_svg
from engine.export import brief_for, bundle_for
from engine.indexer import iter_sections
from engine.journeys import resolve_stop
from engine.render import render_markdown_text
from engine.config import load_config
from engine.drift import build_drift
from engine.fts import SearchIndex
from engine.registry import build_registry
from engine.render import render_doc

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = BASE_DIR / "atlas.config.yaml"


def create_app(config_path: Path | str = DEFAULT_CONFIG) -> FastAPI:
    import threading

    config = load_config(config_path)
    app = FastAPI(title=config.site.title, docs_url=None, redoc_url=None)
    app.state.config = config
    app.state.registry = build_registry(config)
    app.state.search = SearchIndex(config.db_path)
    app.state.search.rebuild(app.state.registry)
    app.state.comments = CommentStore(config.db_path)
    app.state.reindex_lock = threading.Lock()

    templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    def page_context(request: Request, **extra) -> dict:
        registry = request.app.state.registry
        return {
            "site": registry.config.site,
            "grouped": registry.grouped,
            "doc_count": registry.doc_count,
            "curated": registry.curated,
            **extra,
        }

    @app.get("/pygments.css")
    def pygments_stylesheet():
        return Response(pygments_css(), media_type="text/css")

    @app.get("/partial/code", response_class=HTMLResponse)
    def code_partial(request: Request, path: str, symbol: str | None = None):
        registry = request.app.state.registry
        try:
            return HTMLResponse(
                render_file(
                    registry.config.repo_root,
                    path,
                    symbol_index=registry.symbols,
                    symbol=symbol,
                )
            )
        except PanelError as exc:
            safe_path = html_mod.escape(path)
            safe_msg = html_mod.escape(str(exc))
            return HTMLResponse(
                f'<div class="panel-header"><span class="panel-path">{safe_path}</span></div>'
                f'<p class="panel-notice">{safe_msg}</p>',
                status_code=404 if "not found" in str(exc) else 400,
            )

    # ── journeys (issue 012) ──

    def _stop_content(registry, stop) -> str:
        """Render the LIVE target content for a journey stop."""
        reason = resolve_stop(stop, registry)
        if reason is not None:
            return (
                f'<p class="panel-notice">⚠ This stop no longer resolves: '
                f"{html_mod.escape(reason)}. It appears on the drift page.</p>"
            )
        if stop.path:
            try:
                return render_file(
                    registry.config.repo_root,
                    stop.path,
                    symbol_index=registry.symbols,
                    symbol=stop.symbol,
                )
            except PanelError as exc:
                return f'<p class="panel-notice">{html_mod.escape(str(exc))}</p>'
        doc = registry.docs[stop.doc]
        if stop.heading:
            text = doc.path.read_text(encoding="utf-8", errors="replace")
            for heading, slug, body in iter_sections(text):
                if slug == stop.heading:
                    return render_markdown_text(f"## {heading}\n\n{body}")
        return render_doc(doc, registry.docs)

    @app.get("/journey/{journey_id}", response_class=HTMLResponse)
    @app.get("/journey/{journey_id}/{stop_number}", response_class=HTMLResponse)
    def journey_view(request: Request, journey_id: str, stop_number: int = 1):
        registry = request.app.state.registry
        journey = registry.journey(journey_id)
        if journey is None:
            return templates.TemplateResponse(
                request,
                "not_found.html",
                page_context(request, active_id=None, missing_id=f"journey:{journey_id}"),
                status_code=404,
            )
        stop_number = max(1, min(stop_number, len(journey.stops)))
        stop = journey.stops[stop_number - 1]
        return templates.TemplateResponse(
            request,
            "journey.html",
            page_context(
                request,
                active_id=None,
                journey=journey,
                stop=stop,
                stop_number=stop_number,
                total_stops=len(journey.stops),
                narration_html=render_markdown_text(stop.narration),
                content=_stop_content(registry, stop),
            ),
        )

    # ── diagrams (issue 013) ──

    @app.get("/partial/diagram-node", response_class=HTMLResponse)
    def diagram_node_partial(request: Request, diagram: str, node: str):
        registry = request.app.state.registry
        diagram_obj = registry.diagram(diagram)
        node_obj = diagram_obj.node(node) if diagram_obj else None
        if diagram_obj is None or node_obj is None:
            return HTMLResponse("unknown diagram node", status_code=404)
        comment_btn = (
            f'<button class="panel-comment-btn" type="button" title="Comment on this node" '
            f'hx-get="/partial/comments?anchor_kind=diagram-node'
            f'&diagram_id={diagram_obj.id}&node_id={node_obj.id}" '
            f'hx-target="#diagram-thread-{diagram_obj.id}" hx-swap="innerHTML">💬</button>'
        )
        header = (
            f'<div class="panel-header"><span class="panel-path">{html_mod.escape(node_obj.label)}</span>'
            f'<span class="panel-subtitle">{node_obj.type}</span>{comment_btn}</div>'
            f'<p class="dnode-summary">{html_mod.escape(node_obj.summary)}</p>'
            f'<div id="diagram-thread-{diagram_obj.id}" class="comment-thread panel-thread"></div>'
        )
        return HTMLResponse(header + _stop_content(registry, node_obj.as_stop()))

    @app.get("/drift", response_class=HTMLResponse)
    def drift_page(request: Request):
        registry = request.app.state.registry
        report = build_drift(registry)
        claims = sorted(registry.claims, key=lambda r: ("pass", "fail", "error").index(r.status), reverse=True)
        return templates.TemplateResponse(
            request,
            "drift.html",
            page_context(
                request,
                active_id=None,
                report=report,
                claims=claims,
                uncurated=registry.uncurated,
                dangling_stops=registry.dangling_stops,
                dangling_nodes=registry.dangling_nodes,
            ),
        )

    @app.get("/search", response_class=HTMLResponse)
    def search_page(request: Request, q: str = "", scope: str = "all"):
        hits = request.app.state.search.search(q, scope=scope) if q else []
        return templates.TemplateResponse(
            request,
            "search.html",
            page_context(request, active_id=None, q=q, scope=scope, hits=hits),
        )

    @app.get("/partial/search", response_class=HTMLResponse)
    def search_partial(request: Request, q: str = "", scope: str = "all"):
        hits = request.app.state.search.search(q, scope=scope, limit=8) if q.strip() else []
        if not hits:
            return HTMLResponse("")
        items = "".join(
            f'<li><a href="{hit.url}">'
            f'<span class="hit-title">{html_mod.escape(hit.title)}</span>'
            f'<span class="hit-heading">{html_mod.escape(hit.heading)}</span>'
            f"</a></li>"
            for hit in hits
        )
        more = f'<li class="hit-more"><a href="/search?q={html_mod.escape(q)}">All results →</a></li>'
        return HTMLResponse(f'<ul class="search-dropdown">{items}{more}</ul>')

    @app.get("/code/{code_path:path}", response_class=HTMLResponse)
    def code_page(request: Request, code_path: str, symbol: str | None = None):
        registry = request.app.state.registry
        try:
            panel = render_file(
                registry.config.repo_root,
                code_path,
                symbol_index=registry.symbols,
                symbol=symbol,
            )
        except PanelError as exc:
            panel = f'<p class="panel-notice">{html_mod.escape(str(exc))}</p>'
        return templates.TemplateResponse(
            request,
            "code.html",
            page_context(request, active_id=None, code_path=code_path, panel=panel),
        )

    @app.post("/api/reindex")
    def reindex(request: Request):
        """Rebuild the full index and swap it in atomically.

        A new Registry is built off to the side — in-flight requests keep
        serving the old one — then swapped in with a single assignment.
        The lock serializes concurrent triggers (they queue, never interleave).
        """
        with request.app.state.reindex_lock:
            new_registry = build_registry(request.app.state.config)
            fts_rows = request.app.state.search.rebuild(new_registry)
            request.app.state.registry = new_registry  # the atomic swap

        payload = {
            "status": "ok",
            "docs": new_registry.doc_count,
            "fts_rows": fts_rows,
            "build_seconds": new_registry.build_seconds,
            "built_at": new_registry.built_at.isoformat(),
        }
        if request.headers.get("HX-Request"):
            return HTMLResponse(
                f'<span class="reindex-done">✓ {payload["docs"]} docs · '
                f'{payload["fts_rows"]} rows · {payload["build_seconds"]}s</span>'
            )
        return payload

    # ── commenting (issue 009) ──

    def _thread_response(request: Request, anchor: dict, quote: str = ""):
        store = request.app.state.comments
        registry = request.app.state.registry
        comments = mark_orphans(
            store.list(
                anchor_kind=anchor.get("anchor_kind"),
                doc_id=anchor.get("doc_id"),
                heading=anchor.get("heading"),
                path=anchor.get("path"),
                diagram_id=anchor.get("diagram_id"),
                node_id=anchor.get("node_id"),
                journey_id=anchor.get("journey_id"),
                stop_id=anchor.get("stop_id"),
            ),
            registry,
        )
        if anchor.get("anchor_kind") == "doc-section":
            comments = [c for c in comments if c.heading == anchor.get("heading")]
        return templates.TemplateResponse(
            request,
            "partials/comment_thread.html",
            {
                "comments": comments,
                "anchor": anchor,
                "quote": quote,
                "comment_types": COMMENT_TYPES,
            },
        )

    @app.get("/partial/comments", response_class=HTMLResponse)
    def comments_partial(
        request: Request,
        anchor_kind: str,
        doc_id: str | None = None,
        heading: str | None = None,
        path: str | None = None,
        symbol: str | None = None,
        diagram_id: str | None = None,
        node_id: str | None = None,
        journey_id: str | None = None,
        stop_id: str | None = None,
        quote: str = "",
    ):
        anchor = {
            "anchor_kind": anchor_kind,
            "doc_id": doc_id,
            "heading": heading,
            "path": path,
            "symbol": symbol,
            "diagram_id": diagram_id,
            "node_id": node_id,
            "journey_id": journey_id,
            "stop_id": stop_id,
        }
        return _thread_response(request, anchor, quote)

    @app.post("/api/comments", response_class=HTMLResponse)
    def create_comment(
        request: Request,
        anchor_kind: str = Form(...),
        type: str = Form(...),
        body: str = Form(...),
        quote: str = Form(""),
        doc_id: str = Form(""),
        heading: str = Form(""),
        path: str = Form(""),
        symbol: str = Form(""),
        diagram_id: str = Form(""),
        node_id: str = Form(""),
        journey_id: str = Form(""),
        stop_id: str = Form(""),
    ):
        store = request.app.state.comments
        try:
            store.create(
                anchor_kind=anchor_kind,
                type=type,
                body=body,
                quote=quote or None,
                doc_id=doc_id or None,
                heading=heading or None,
                path=path or None,
                symbol=symbol or None,
                diagram_id=diagram_id or None,
                node_id=node_id or None,
                journey_id=journey_id or None,
                stop_id=stop_id or None,
            )
        except ValueError as exc:
            return HTMLResponse(
                f'<p class="panel-notice">{html_mod.escape(str(exc))}</p>', status_code=400
            )
        anchor = {
            "anchor_kind": anchor_kind,
            "doc_id": doc_id or None,
            "heading": heading or None,
            "path": path or None,
            "symbol": symbol or None,
            "diagram_id": diagram_id or None,
            "node_id": node_id or None,
            "journey_id": journey_id or None,
            "stop_id": stop_id or None,
        }
        return _thread_response(request, anchor)

    @app.post("/api/comments/{comment_id}/status", response_class=HTMLResponse)
    def set_comment_status(
        request: Request,
        comment_id: str,
        status: str = Form(...),
        resolution_note: str = Form(""),
    ):
        store = request.app.state.comments
        try:
            comment = store.set_status(comment_id, status, resolution_note or None)
        except ValueError as exc:
            return HTMLResponse(html_mod.escape(str(exc)), status_code=400)
        if comment is None:
            return HTMLResponse("not found", status_code=404)
        mark_orphans([comment], request.app.state.registry)
        return templates.TemplateResponse(
            request,
            "partials/feedback_row.html",
            {"comment": comment, "statuses": STATUSES},
        )

    @app.get("/api/comments/bundle")
    def comment_bundle(
        request: Request,
        status: str = "open",
        type: str = "",
        doc: str = "",
    ):
        store = request.app.state.comments
        registry = request.app.state.registry
        comments = mark_orphans(
            store.list(status=status or None, type=type or None, doc_id=doc or None),
            registry,
        )
        return Response(
            bundle_for(comments, registry), media_type="text/markdown; charset=utf-8"
        )

    @app.get("/api/comments/{comment_id}/brief")
    def comment_brief(request: Request, comment_id: str):
        store = request.app.state.comments
        comment = store.get(comment_id)
        if comment is None:
            return Response("not found", status_code=404, media_type="text/plain")
        registry = request.app.state.registry
        mark_orphans([comment], registry)
        return Response(
            brief_for(comment, registry), media_type="text/markdown; charset=utf-8"
        )

    @app.post("/api/comments/{comment_id}/delete", response_class=HTMLResponse)
    def delete_comment(request: Request, comment_id: str):
        request.app.state.comments.delete(comment_id)
        return HTMLResponse("")

    @app.get("/feedback", response_class=HTMLResponse)
    def feedback_page(
        request: Request,
        status: str = "",
        type: str = "",
        doc: str = "",
    ):
        store = request.app.state.comments
        comments = mark_orphans(
            store.list(status=status or None, type=type or None, doc_id=doc or None),
            request.app.state.registry,
        )
        all_comments = store.list()
        return templates.TemplateResponse(
            request,
            "feedback.html",
            page_context(
                request,
                active_id=None,
                comments=comments,
                statuses=STATUSES,
                comment_types=COMMENT_TYPES,
                filter_status=status,
                filter_type=type,
                filter_doc=doc,
                total=len(all_comments),
                open_count=sum(1 for c in all_comments if c.status == "open"),
            ),
        )

    @app.get("/healthz")
    def healthz(request: Request):
        registry = request.app.state.registry
        return {
            "status": "ok",
            "docs": registry.doc_count,
            "built_at": registry.built_at.isoformat(),
            "build_seconds": registry.build_seconds,
        }

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        return templates.TemplateResponse(
            request,
            "home.html",
            page_context(request, active_id=None, journeys=request.app.state.registry.journeys),
        )

    @app.get("/raw/{raw_path:path}")
    def raw_file(request: Request, raw_path: str):
        registry = request.app.state.registry
        try:
            target = safe_resolve(registry.config.repo_root, raw_path)
        except PanelError as exc:
            return HTMLResponse(html_mod.escape(str(exc)), status_code=400)
        if not target.is_file():
            return HTMLResponse("not found", status_code=404)
        media_type = mimetypes.guess_type(target.name)[0] or "text/plain"
        return FileResponse(target, media_type=media_type)

    @app.get("/doc/{doc_id:path}", response_class=HTMLResponse)
    def doc_view(request: Request, doc_id: str):
        registry = request.app.state.registry
        doc = registry.docs.get(doc_id)
        if doc is None:
            return templates.TemplateResponse(
                request,
                "not_found.html",
                page_context(request, active_id=None, missing_id=doc_id),
                status_code=404,
            )

        artifact_link = registry.artifact_links.get(doc.id)

        # External docs (e.g. site/ HTML) link out rather than render inline.
        if doc.render == "external":
            return templates.TemplateResponse(
                request,
                "external.html",
                page_context(request, active_id=doc.id, doc=doc, artifact_link=artifact_link),
            )

        # Non-markdown corpus docs (e.g. agent prompt .ts files) render as code.
        if not doc.is_markdown:
            try:
                panel = render_file(
                    registry.config.repo_root, doc.id, symbol_index=registry.symbols
                )
            except PanelError as exc:
                panel = f'<p class="panel-notice">{html_mod.escape(str(exc))}</p>'
            return templates.TemplateResponse(
                request,
                "code.html",
                page_context(
                    request,
                    active_id=doc.id,
                    code_path=doc.id,
                    panel=panel,
                    artifact_link=artifact_link,
                ),
            )

        content = render_doc(doc, registry.docs)

        # Mark failing quantitative claims at the quoted sentence (banner fallback).
        failing_claims = registry.failing_claims_for(doc.id)
        for result in failing_claims:
            quoted = html_mod.escape(result.claim.quote, quote=False)
            marked = (
                f'<mark class="claim-drift" title="{html_mod.escape(result.message)}">'
                f"{quoted}</mark>"
            )
            if quoted in content:
                content = content.replace(quoted, marked, 1)

        backlinks = sorted(
            (d for d in registry.docs.values() if doc.id in d.links),
            key=lambda d: d.title.lower(),
        )
        return templates.TemplateResponse(
            request,
            "doc.html",
            page_context(
                request,
                active_id=doc.id,
                doc=doc,
                content=content,
                backlinks=backlinks,
                failing_claims=failing_claims,
                artifact_link=artifact_link,
                section_comment_counts=request.app.state.comments.counts_by_section(doc.id),
                diagrams=[
                    (d, render_svg(d)) for d in registry.diagrams_for(doc.id)
                ],
            ),
        )

    return app


# Lazy module-level `app`: `uvicorn app:app` resolves this attribute and builds
# the application on demand, but plainly importing this module (e.g. the test
# suite, or tooling) does NOT require a deployed atlas.config.yaml to exist.
_app = None


def __getattr__(name):  # PEP 562
    if name == "app":
        global _app
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if __name__ == "__main__":
    import uvicorn

    application = create_app()
    uvicorn.run(application, host="127.0.0.1", port=application.state.registry.config.port)
