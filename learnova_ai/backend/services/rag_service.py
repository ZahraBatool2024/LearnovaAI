"""
Course-specific RAG — corrected to add new material incrementally instead
of rebuilding the whole course index on every upload.

Embedding strategy, in order of preference:
  1. sentence-transformers (semantic, dense, fixed-size vectors) — used if
     the package + model are available locally (downloaded once, then
     fully offline).
  2. HashingVectorizer (scikit-learn) fallback — no model download AND no
     fitting step, unlike TF-IDF. Because it's stateless, a brand-new
     chunk can be embedded and appended to an existing FAISS index on its
     own, with zero recomputation of anything already indexed. This is
     what makes incremental indexing possible without a real embedding
     model.

Both backends produce fixed-length vectors, so both support true
incremental `index.add()` — the previous version's full-rebuild-per-upload
is gone.

Each course gets its own FAISS index file + id-map file under
backend/data/vector_store/, so retrieval never crosses course boundaries.
"""

import os
import json
import numpy as np
import faiss

VECTOR_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "vector_store")
os.makedirs(VECTOR_DIR, exist_ok=True)

HASHING_DIM = 1024  # fixed dimensionality for the no-model fallback

_SEMANTIC_MODEL = None
_SEMANTIC_TRIED = False


def _get_semantic_model():
    """Lazily try to load a local sentence-transformers model. Returns None
    (and stays None afterward) if the package or model isn't available —
    callers fall back to hashing embeddings automatically."""
    global _SEMANTIC_MODEL, _SEMANTIC_TRIED
    if _SEMANTIC_TRIED:
        return _SEMANTIC_MODEL
    _SEMANTIC_TRIED = True
    try:
        from sentence_transformers import SentenceTransformer
        _SEMANTIC_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
    except Exception:
        _SEMANTIC_MODEL = None
    return _SEMANTIC_MODEL


def _hashing_vectorizer():
    from sklearn.feature_extraction.text import HashingVectorizer
    # alternate_sign=False + norm="l2" makes cosine similarity via inner
    # product meaningful, same as the semantic path.
    return HashingVectorizer(n_features=HASHING_DIM, alternate_sign=False, norm="l2", stop_words="english")


def _embed(texts):
    """Returns (vectors: float32 ndarray, backend_name: str). Stateless for
    both backends, so it works identically on 1 new chunk or 1000."""
    model = _get_semantic_model()
    if model is not None:
        vectors = np.asarray(model.encode(texts, normalize_embeddings=True), dtype="float32")
        return vectors, "semantic"
    vectorizer = _hashing_vectorizer()
    vectors = vectorizer.transform(texts).toarray().astype("float32")
    return vectors, "hashing"


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 120):
    """Simple sliding-window chunker over characters. Good enough for a
    foundation; swap for a token-aware splitter if you move to a real LLM
    with strict context limits."""
    text = " ".join(text.split())
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return chunks


def _index_paths(course_id: str):
    return (
        os.path.join(VECTOR_DIR, f"course_{course_id}.index"),
        os.path.join(VECTOR_DIR, f"course_{course_id}.meta.json"),
    )


def _load_index(course_id: str, dim: int, backend: str):
    index_path, meta_path = _index_paths(course_id)
    if os.path.exists(index_path) and os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        # Return the existing metadata even when its backend differs. The
        # caller must see that mismatch so it can rebuild all course chunks.
        return faiss.read_index(index_path), meta
    return faiss.IndexFlatIP(dim), {"backend": backend, "chunk_ids": []}


def add_chunks_to_index(course_id: str, new_chunks: list, db):
    """`new_chunks` is a list of DocumentChunk rows just inserted for one
    upload. Embeds ONLY these, appends them to the course's existing FAISS
    index, and updates each row's `vector_row`. Chunks already indexed from
    earlier uploads are untouched — no recomputation, no rebuild."""
    if not new_chunks:
        return

    texts = [c.text for c in new_chunks]
    vectors, backend = _embed(texts)
    index, meta = _load_index(course_id, vectors.shape[1], backend)

    if meta.get("backend") != backend:
        # Backend changed since the index was created — rebuild first, then
        # append the new upload. The rebuild includes the newly inserted chunks.
        return _rebuild_from_backend_change(course_id, backend, db)

    start_row = index.ntotal
    index.add(vectors)

    for offset, chunk in enumerate(new_chunks):
        chunk.vector_row = start_row + offset
    db.commit()

    meta["chunk_ids"].extend(c.id for c in new_chunks)
    index_path, meta_path = _index_paths(course_id)
    faiss.write_index(index, index_path)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f)


def _rebuild_from_backend_change(course_id: str, backend: str, db):
    from backend.models import DocumentChunk
    all_chunks = db.query(DocumentChunk).filter(DocumentChunk.course_id == course_id).order_by(DocumentChunk.id).all()
    if not all_chunks:
        return
    texts = [c.text for c in all_chunks]
    vectors, confirmed_backend = _embed(texts)
    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)
    for row, chunk in enumerate(all_chunks):
        chunk.vector_row = row
    db.commit()
    index_path, meta_path = _index_paths(course_id)
    faiss.write_index(index, index_path)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({"backend": confirmed_backend, "chunk_ids": [c.id for c in all_chunks]}, f)


def rebuild_course_index(course_id: str, db):
    """Rebuild a course index from its remaining DB chunks. Used after document deletion."""
    from backend.models import DocumentChunk
    chunks = db.query(DocumentChunk).filter(DocumentChunk.course_id == course_id).order_by(DocumentChunk.id).all()
    index_path, meta_path = _index_paths(course_id)
    if not chunks:
        for path in (index_path, meta_path):
            if os.path.exists(path):
                os.remove(path)
        return
    texts = [c.text for c in chunks]
    vectors, backend = _embed(texts)
    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)
    for row, chunk in enumerate(chunks):
        chunk.vector_row = row
    db.commit()
    faiss.write_index(index, index_path)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({"backend": backend, "chunk_ids": [c.id for c in chunks]}, f)


def retrieve(course_id: str, query: str, top_k: int = 5, db=None):
    """Returns a list of {text, score, chunk_id} for the most relevant chunks
    in this course. Returns [] if the course has no indexed material yet."""
    index_path, meta_path = _index_paths(course_id)
    if not (os.path.exists(index_path) and os.path.exists(meta_path)):
        return []

    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    index = faiss.read_index(index_path)
    if meta["backend"] == "semantic":
        model = _get_semantic_model()
        if model is None:
            return []  # backend mismatch (model no longer available) — caller should re-ingest
        qvec = np.asarray(model.encode([query], normalize_embeddings=True), dtype="float32")
    else:
        qvec = _hashing_vectorizer().transform([query]).toarray().astype("float32")

    k = min(top_k, index.ntotal)
    if k == 0:
        return []
    scores, rows = index.search(qvec, k)

    from backend.models import DocumentChunk
    chunk_ids = meta["chunk_ids"]
    results = []
    for score, row in zip(scores[0], rows[0]):
        if row < 0 or row >= len(chunk_ids):
            continue
        chunk = db.query(DocumentChunk).filter(DocumentChunk.id == chunk_ids[row]).first()
        if chunk:
            results.append({"text": chunk.text, "score": float(score), "chunk_id": chunk.id})
    return results


def delete_course_index(course_id: str):
    for suffix in (".index", ".meta.json"):
        path = os.path.join(VECTOR_DIR, f"course_{course_id}{suffix}")
        if os.path.exists(path):
            os.remove(path)
