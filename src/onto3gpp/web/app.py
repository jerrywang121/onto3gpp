"""FastAPI application for the onto3gpp web interface.

Loads the compiled dictionary, ontology, and parsed chunks once at startup,
builds the BM25 index, and exposes read-only endpoints:

  POST /api/query     — run a query with configurable parameters.
  GET  /api/concepts  — list concepts, filtered by text/type.
  GET  /api/graph     — neighborhood subgraph of the ontology topology.
  GET  /api/meta      — corpus statistics.

The runtime stays deterministic and CPU-only; the web layer is a thin,
stateless wrapper over the existing search/reasoning code.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from onto3gpp.compile.dictionary import Dictionary
from onto3gpp.ontology.schema import Ontology, ontology_from_dict
from onto3gpp.parser import extract_pdf_text, parse_text
from onto3gpp.runtime.ner_chain import NERChain
from onto3gpp.runtime.reasoner import reason
from onto3gpp.runtime.reranker import rerank
from onto3gpp.search.bm25 import BM25Index
from onto3gpp.search.chunker import Chunk, chunk_sections
from onto3gpp.search.chunker import load_chunks as load_chunks_from_dir

STATIC_DIR = Path(__file__).parent / "static"

# A spec number is a dotted numeric identifier like "23.501" or "38300".
_SPEC_RE = re.compile(r"^\d+(?:\.\d+)*$")


def _spec_from_filename(filename: str) -> str:
    """Derive a spec number from a PDF filename.

    Handles common 3GPP naming patterns: ``ts_23501v190700p.pdf`` →
    ``23.501``, ``ts_38300v190000p.pdf`` → ``38.300``, ``38300-i30.pdf`` →
    ``38.300``. A numeric run of 5+ digits is formatted in the standard
    ``XX.NNN`` spec form (dot before the last three digits). Returns ``""``
    if no spec number can be found.
    """
    stem = Path(filename).stem
    # Strip a leading "ts_" / "tr_" prefix and a trailing version like
    # "v190700p" or "-i30".
    m = re.search(r"(?:ts|tr)_?(\d+(?:\.\d+)*)", stem, re.IGNORECASE)
    if not m:
        m = re.search(r"(\d+(?:\.\d+)*)", stem)
    if not m:
        return ""
    digits = m.group(1).replace(".", "")
    if len(digits) >= 5:
        return f"{digits[:-3]}.{digits[-3:]}"
    return digits


def load_chunks(parsed_dir: Path, max_chars: int = 500, overlap: int = 80) -> list[Chunk]:
    """Load chunks from a directory of parsed JSONL files."""
    return load_chunks_from_dir(parsed_dir, max_chars=max_chars, overlap=overlap)


class Runtime:
    """Holds the loaded index, dictionary, and ontology for the app."""

    def __init__(
        self,
        chunks: list[Chunk],
        dictionary: Dictionary | None,
        onto: Ontology | None,
    ) -> None:
        self.chunks = chunks
        self.index = BM25Index.build(chunks)
        self.dictionary = dictionary
        self.ontology = onto

    def add_chunks(self, new_chunks: list[Chunk]) -> None:
        """Append chunks and rebuild the BM25 index to include them."""
        if not new_chunks:
            return
        self.chunks.extend(new_chunks)
        self.index = BM25Index.build(self.chunks)


def build_runtime(
    parsed_dir: Path,
    dict_path: Path | None = None,
    ontology_path: Path | None = None,
    max_chars: int = 500,
    overlap: int = 80,
) -> Runtime:
    """Build the runtime state from data files."""
    chunks = load_chunks(parsed_dir, max_chars=max_chars, overlap=overlap)

    dictionary = None
    if dict_path is not None and dict_path.exists():
        dictionary = Dictionary.from_dict(
            json.loads(dict_path.read_text(encoding="utf-8"))
        )

    ontology = None
    if ontology_path is not None and ontology_path.exists():
        ontology = ontology_from_dict(
            json.loads(ontology_path.read_text(encoding="utf-8"))
        )

    return Runtime(chunks, dictionary, ontology)


def create_app(
    parsed_dir: Path,
    dict_path: Path | None = None,
    ontology_path: Path | None = None,
    max_chars: int = 500,
    overlap: int = 80,
) -> FastAPI:
    """Create the FastAPI app with the given data paths."""
    runtime = build_runtime(
        parsed_dir,
        dict_path,
        ontology_path,
        max_chars=max_chars,
        overlap=overlap,
    )

    app = FastAPI(title="onto3gpp explorer", version="0.1.0")
    app.state.runtime = runtime

    @app.get("/api/meta")
    def meta() -> dict:
        """Corpus statistics."""
        specs: dict[str, int] = {}
        for c in runtime.chunks:
            specs[c.spec] = specs.get(c.spec, 0) + 1
        return {
            "chunks": len(runtime.chunks),
            "specs": specs,
            "concepts": len(runtime.ontology.concepts) if runtime.ontology else 0,
            "relations": len(runtime.ontology.relations) if runtime.ontology else 0,
            "dictionary_entries": len(runtime.dictionary.entries)
            if runtime.dictionary
            else 0,
        }

    @app.post("/api/upload")
    async def upload(
        file: UploadFile = File(...),
        release: str = Form("Rel-18"),
        spec: str = Form(""),
        max_chars: int = Form(max_chars),
        overlap: int = Form(overlap),
    ) -> dict:
        """Upload a PDF, parse it into sections, persist them, and update the
        live index so new content is immediately searchable.

        The spec number is taken from the ``spec`` form field if provided,
        otherwise derived from the filename (e.g. ``ts_23501v190700p.pdf`` →
        ``23.501``). The parsed JSONL is appended to ``<parsed_dir>/<spec>.jsonl``
        and the runtime index is rebuilt to include the new chunks. The chunk
        ``max_chars`` and ``overlap`` parameters default to the app's configured
        values but can be overridden per upload.
        """
        if not file.filename:
            raise HTTPException(status_code=400, detail="no file provided")
        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="only PDF files are supported")

        # Derive the spec number from the filename if not given explicitly.
        spec = spec.strip()
        if not spec:
            spec = _spec_from_filename(file.filename)
        if not spec:
            raise HTTPException(
                status_code=400,
                detail=(
                    "could not determine a spec number from the filename; "
                    "provide one via the spec field"
                ),
            )

        # Read the uploaded bytes and extract text.
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="empty file")
        tmp = Path(file.filename or "upload.pdf")
        tmp.write_bytes(data)
        try:
            text = extract_pdf_text(tmp)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            tmp.unlink(missing_ok=True)

        if not text.strip():
            raise HTTPException(status_code=400, detail="no text could be extracted from the PDF")

        sections = parse_text(text, spec=spec, release=release)
        if not sections:
            raise HTTPException(status_code=400, detail="no sections parsed from the PDF")

        # Persist the parsed sections to the parsed directory.
        parsed_dir.mkdir(parents=True, exist_ok=True)
        out_path = parsed_dir / f"{spec}.jsonl"
        with out_path.open("a", encoding="utf-8") as f:
            for s in sections:
                f.write(json.dumps(s.__dict__) + "\n")

        # Update the live runtime so the new content is searchable immediately.
        new_chunks = chunk_sections(sections, max_chars=max_chars, overlap=overlap)
        runtime.add_chunks(new_chunks)

        return {
            "spec": spec,
            "release": release,
            "max_chars": max_chars,
            "overlap": overlap,
            "sections": len(sections),
            "chunks": len(new_chunks),
            "total_chunks": len(runtime.chunks),
            "parsed_file": str(out_path),
        }

    @app.post("/api/query")
    def query(
        body: dict,
    ) -> dict:
        """Run a query with configurable parameters and return ranked results."""
        q = (body.get("query") or "").strip()
        if not q:
            raise HTTPException(status_code=400, detail="query is required")

        top_k = int(body.get("top_k", 10))
        max_hops = int(body.get("max_hops", 1))
        fuzzy_threshold = float(body.get("fuzzy_threshold", 0.0))
        use_chain = bool(body.get("use_chain", True))
        use_ontology = bool(body.get("use_ontology", True))
        use_structure = bool(body.get("use_structure", True))

        if runtime.ontology is None:
            use_ontology = False
            use_structure = False
        if runtime.dictionary is None:
            use_chain = False

        # Build the search plan (primary + related terms) for the trace.
        plan = None
        if runtime.ontology is not None:
            plan = reason(q, runtime.ontology, max_hops=max_hops)

        # Run the appropriate search path.
        if use_ontology:
            dict_for_chain = runtime.dictionary if use_chain else None
            results = runtime.index.search_structure(
                q,
                runtime.ontology,
                dictionary=dict_for_chain,
                top_k=top_k,
                max_hops=max_hops,
                fuzzy_threshold=fuzzy_threshold,
            )
            if use_structure:
                results = rerank(
                    results,
                    q,
                    runtime.ontology,
                    chunks=runtime.chunks,
                )
        elif use_chain and runtime.dictionary is not None:
            results = runtime.index.search_expanded(q, runtime.dictionary, top_k=top_k)
        else:
            results = runtime.index.search(q, top_k=top_k)

        # NER matches (for the trace).
        ner_matches = []
        if runtime.dictionary is not None and runtime.ontology is not None:
            chain = NERChain(
                runtime.dictionary, runtime.ontology, fuzzy_threshold=fuzzy_threshold
            )
            ner_matches = [
                {"canonical": m.canonical, "level": m.level, "surface": m.surface}
                for m in chain.annotate(q)
            ]

        return {
            "query": q,
            "params": {
                "top_k": top_k,
                "max_hops": max_hops,
                "fuzzy_threshold": fuzzy_threshold,
                "use_chain": use_chain,
                "use_ontology": use_ontology,
                "use_structure": use_structure,
            },
            "plan": {
                "primary_terms": plan.primary_terms if plan else [],
                "related_terms": plan.related_terms if plan else [],
                "explanation": plan.explanation if plan else [],
            },
            "ner_matches": ner_matches,
            "results": [
                {
                    "rank": i + 1,
                    "score": round(r.score, 4),
                    "spec": r.chunk.spec,
                    "clause": r.chunk.clause,
                    "title": r.chunk.title,
                    "text": r.chunk.text,
                }
                for i, r in enumerate(results)
            ],
        }

    @app.get("/api/concepts")
    def concepts(
        q: str = Query("", description="Filter by text (canonical or alias)"),
        type: str = Query("", description="Filter by concept type"),
        limit: int = Query(100, ge=1, le=1000),
    ) -> dict:
        """List concepts, optionally filtered by text and/or type."""
        if runtime.ontology is None:
            raise HTTPException(status_code=404, detail="no ontology loaded")
        needle = q.strip().lower()
        out = []
        for c in runtime.ontology.concepts:
            if type and c.type != type:
                continue
            if needle:
                hay = " ".join([c.canonical, c.id, *c.aliases]).lower()
                if needle not in hay:
                    continue
            out.append(
                {
                    "id": c.id,
                    "canonical": c.canonical,
                    "type": c.type,
                    "aliases": list(c.aliases),
                }
            )
            if len(out) >= limit:
                break
        return {"total": len(out), "concepts": out}

    @app.get("/api/graph")
    def graph(
        concept: str = Query("", description="Concept id or canonical to center on"),
        radius: int = Query(1, ge=1, le=3),
        limit: int = Query(200, ge=1, le=2000),
    ) -> dict:
        """Return the neighborhood subgraph around a concept (BFS up to radius)."""
        if runtime.ontology is None:
            raise HTTPException(status_code=404, detail="ontology not loaded")
        onto = runtime.ontology

        # Resolve the center concept by id or canonical.
        center_id = None
        for c in onto.concepts:
            if c.id == concept or c.canonical.lower() == concept.lower():
                center_id = c.id
                break
        if center_id is None:
            raise HTTPException(status_code=404, detail=f"concept not found: {concept}")

        # BFS to collect nodes within `radius` hops.
        adj: dict[str, list[str]] = {}
        for r in onto.relations:
            adj.setdefault(r.source, []).append(r.target)
            adj.setdefault(r.target, []).append(r.source)

        visited: set[str] = {center_id}
        frontier: list[str] = [center_id]
        for _ in range(radius):
            nxt: list[str] = []
            for node in frontier:
                for nb in adj.get(node, []):
                    if nb not in visited:
                        visited.add(nb)
                        nxt.append(nb)
            frontier = nxt
            if not frontier:
                break

        # Collect nodes (capped) and the edges among them.
        node_ids = list(visited)[:limit]
        node_set = set(node_ids)
        nodes = [
            {
                "id": c.id,
                "canonical": c.canonical,
                "type": c.type,
                "is_center": c.id == center_id,
            }
            for c in onto.concepts
            if c.id in node_set
        ]
        edges = [
            {"source": r.source, "rel": r.rel, "target": r.target}
            for r in onto.relations
            if r.source in node_set and r.target in node_set
        ]
        return {"center": center_id, "nodes": nodes, "edges": edges}

    # Serve the static frontend.
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(str(STATIC_DIR / "index.html"))

    return app
