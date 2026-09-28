"""
Embedding-based (dense) retrieval over the markdown knowledge base.

Why embeddings instead of TF-IDF:
- Support tickets rarely reuse the KB's exact wording ("can't log in"
  vs. "AUTH_TOKEN_EXPIRED" vs. "SSO group not mapped") - dense vectors
  capture that semantic similarity, sparse keyword matching misses it.
- Runs fully locally via sentence-transformers: the model is downloaded
  once and cached, ticket text never leaves the process to compute a
  match (see design note's data-sensitivity section).
- Embeddings are deterministic for a fixed model + input, so KB match
  results are still reproducible across runs.

Chunking follows the strategy recommended in DATA_SCHEMA.md:
- Split on `---` horizontal rules (major section boundaries)
- Preserve heading hierarchy as metadata
- Markdown table rows become their own atomic chunk (good for
  error-code lookups like "AUTH_TOKEN_EXPIRED")
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

from . import config


@dataclass
class Chunk:
    doc_path: str          # relative path, e.g. "troubleshooting/authentication-sso.md"
    heading_path: str      # e.g. "Troubleshooting: Authentication & SSO > Error Reference"
    text: str               # chunk content used for retrieval + display


def _current_heading_stack(lines: list[str], upto_idx: int) -> list[str]:
    """Walk backwards from a line index to reconstruct the active heading
    hierarchy (h1 > h2 > ...) at that point in the document."""
    stack: dict[int, str] = {}
    for i in range(upto_idx, -1, -1):
        m = re.match(r"^(#{1,6})\s+(.*)$", lines[i])
        if m:
            level = len(m.group(1))
            title = m.group(2).strip()
            if level not in stack:
                stack[level] = title
            # once we've captured the shallowest heading (h1) we can stop early
            if level == 1:
                break
    return [stack[lvl] for lvl in sorted(stack)]


def _chunk_markdown(doc_path: str, raw_text: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    lines = raw_text.splitlines()

    # 1. Split on '---' horizontal rules into major sections
    sections: list[tuple[int, list[str]]] = []  # (start_line_idx, lines)
    current: list[str] = []
    current_start = 0
    for i, line in enumerate(lines):
        if line.strip() == "---":
            if current:
                sections.append((current_start, current))
            current = []
            current_start = i + 1
        else:
            current.append(line)
    if current:
        sections.append((current_start, current))

    for start_idx, sec_lines in sections:
        sec_text = "\n".join(sec_lines).strip()
        if not sec_text:
            continue

        heading_stack = _current_heading_stack(lines, start_idx)
        heading_path = " > ".join(heading_stack) if heading_stack else Path(doc_path).stem

        # 2. Within a section, break out markdown tables so each row is
        #    its own atomic chunk (error-code lookups), keep the rest as
        #    one prose chunk.
        table_rows: list[str] = []
        prose_lines: list[str] = []
        in_table = False
        header_cols: list[str] | None = None

        for line in sec_lines:
            stripped = line.strip()
            is_table_row = stripped.startswith("|") and stripped.endswith("|")
            is_separator_row = bool(re.match(r"^\|[\s:|-]+\|$", stripped))

            if is_table_row and not is_separator_row:
                cols = [c.strip() for c in stripped.strip("|").split("|")]
                if header_cols is None:
                    header_cols = cols
                    in_table = True
                    continue
                # data row -> render as "Header: value" pairs, one atomic chunk
                pairs = [f"{h}: {v}" for h, v in zip(header_cols, cols)]
                table_rows.append("; ".join(pairs))
            elif is_separator_row:
                continue
            else:
                if in_table:
                    # table ended
                    in_table = False
                    header_cols = None
                if stripped:
                    prose_lines.append(line)

        if prose_lines:
            prose_text = "\n".join(prose_lines).strip()
            # Skip chunks that are *only* heading lines (e.g. a lone "##
            # Error Reference" right before a table). Their information is
            # already captured in heading_path for every other chunk in
            # this section, so indexing them separately just adds noise
            # that can outrank genuinely useful prose in retrieval (a bare
            # heading like "Error Reference" can score deceptively high
            # against queries that mention "error").
            non_heading_lines = [
                ln for ln in prose_lines
                if not re.match(r"^\s{0,3}#{1,6}\s+.*$", ln) and ln.strip()
            ]
            if non_heading_lines:
                chunks.append(Chunk(doc_path=doc_path, heading_path=heading_path, text=prose_text))
        for row in table_rows:
            chunks.append(Chunk(doc_path=doc_path, heading_path=heading_path, text=row))

    return chunks


_MODEL_LOCK = threading.Lock()
_MODEL_CACHE: dict[str, SentenceTransformer] = {}


def _load_model(name: str) -> SentenceTransformer:
    """Load (and cache) the sentence-transformers model. Cached at module
    level because loading it is the expensive part - reused across every
    KBRetriever instance in the process."""
    with _MODEL_LOCK:
        if name not in _MODEL_CACHE:
            _MODEL_CACHE[name] = SentenceTransformer(name)
        return _MODEL_CACHE[name]


def _cosine_sim_matrix(query_vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    # embeddings from sentence-transformers are L2-normalisable; normalise
    # explicitly here so this works even if normalize_embeddings=False.
    q = query_vec / (np.linalg.norm(query_vec) + 1e-12)
    m = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-12)
    return m @ q


class KBRetriever:
    def __init__(self, kb_dir: Path = config.KB_DIR, model_name: str = config.EMBEDDING_MODEL):
        self.kb_dir = Path(kb_dir)
        self.model_name = model_name
        self.chunks: list[Chunk] = []
        self._embeddings: np.ndarray | None = None
        self._model: SentenceTransformer | None = None
        self._build()

    def _build(self) -> None:
        md_files = sorted(self.kb_dir.rglob("*.md"))
        for path in md_files:
            rel_path = str(path.relative_to(self.kb_dir))
            raw = path.read_text(encoding="utf-8")
            self.chunks.extend(_chunk_markdown(rel_path, raw))

        if not self.chunks:
            raise RuntimeError(f"No markdown chunks found under {self.kb_dir}")

        self._model = _load_model(self.model_name)
        corpus = [f"{c.heading_path}\n{c.text}" for c in self.chunks]
        self._embeddings = self._model.encode(
            corpus, convert_to_numpy=True, show_progress_bar=False
        )

    def search(self, query: str, top_k: int = config.KB_TOP_K) -> list[tuple[Chunk, float]]:
        if not query.strip():
            return []
        query_vec = self._model.encode([query], convert_to_numpy=True, show_progress_bar=False)[0]
        sims = _cosine_sim_matrix(query_vec, self._embeddings)
        ranked_idx = sims.argsort()[::-1][:top_k]
        return [(self.chunks[i], float(sims[i])) for i in ranked_idx if sims[i] > 0]


# Module-level singleton so the index (and model) is built once per process
_retriever: KBRetriever | None = None


def get_retriever() -> KBRetriever:
    global _retriever
    if _retriever is None:
        _retriever = KBRetriever()
    return _retriever
