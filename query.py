"""
Query the hybrid index built by index.py.

Usage:
  python3 query.py                  # interactive REPL
  python3 query.py "sick leave"     # one-shot
  python3 query.py --top 5 "..."    # return top 5 results
"""
import re
import sys
import pickle
import pathlib
import argparse
import textwrap
import chromadb

INDEX_DIR = pathlib.Path(__file__).parent / ".index"
DOCS_DIR  = pathlib.Path(__file__).parent / "docs"

TOP_K       = 5    # results to surface
BODY_PREVIEW = 600  # chars of body shown per result


def load_indexes():
    client = chromadb.PersistentClient(path=str(INDEX_DIR / "chroma"))
    col = client.get_collection("un2018")
    with open(INDEX_DIR / "bm25.pkl", "rb") as f:
        bm25_data = pickle.load(f)
    return col, bm25_data


def hybrid_search(question: str, col, bm25_data, top_k: int = TOP_K):
    tokenize = lambda s: re.findall(r'\w+', s.lower())
    docs_meta = bm25_data["docs"]
    bodies    = bm25_data["bodies"]
    bm25      = bm25_data["bm25"]
    n         = len(docs_meta)

    # ── BM25 scores (normalized 0-1) ──────────────────────────
    bm25_scores = bm25.get_scores(tokenize(question))
    bm25_max    = max(bm25_scores) or 1.0
    bm25_norm   = [s / bm25_max for s in bm25_scores]

    # ── ChromaDB vector scores (distance → similarity) ────────
    n_query = min(top_k * 3, n)
    vres = col.query(query_texts=[question], n_results=n_query,
                     include=["distances", "metadatas"])
    vec_ids   = vres["ids"][0]
    vec_dists = vres["distances"][0]

    # Build a lookup: doc_id → vector similarity (1 - normalized distance)
    vec_scores = {}
    if vec_dists:
        max_dist = max(vec_dists) or 1.0
        for doc_id, dist in zip(vec_ids, vec_dists):
            vec_scores[doc_id] = 1.0 - dist / max_dist

    # ── Combine scores (equal weight) ─────────────────────────
    combined = []
    for i, meta in enumerate(docs_meta):
        doc_id  = meta["id"]
        bm25_s  = bm25_norm[i]
        vec_s   = vec_scores.get(doc_id, 0.0)
        score   = 0.5 * bm25_s + 0.5 * vec_s
        combined.append((score, i))

    combined.sort(reverse=True)
    return [(score, docs_meta[i], bodies[i]) for score, i in combined[:top_k]]


def fmt_result(rank: int, score: float, meta: dict, body: str) -> str:
    lines = []
    lines.append(f"\n{'─'*60}")
    lines.append(f"#{rank}  [{meta['kind'].upper()}]  {meta['title']}")
    lines.append(f"    Source: un2018.pdf, p. {meta['page']}  |  score: {score:.3f}")
    if meta.get("number"):
        lines.append(f"    Number: {meta['number']}  |  Section: {meta['section']}")
    lines.append("")
    preview = body[:BODY_PREVIEW].strip()
    if len(body) > BODY_PREVIEW:
        preview += " …"
    for line in textwrap.wrap(preview, width=76):
        lines.append("  " + line)
    return "\n".join(lines)


def run(question: str, col, bm25_data, top_k: int):
    results = hybrid_search(question, col, bm25_data, top_k)
    print(f'\nTop {top_k} results for: "{question}"')
    for rank, (score, meta, body) in enumerate(results, 1):
        print(fmt_result(rank, score, meta, body))
    print(f"\n{'─'*60}")
    print("Tip: open the full file at docs/<section>/<filename>.md")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("question", nargs="?", default=None)
    parser.add_argument("--top", type=int, default=TOP_K)
    args = parser.parse_args()

    print("Loading index…", end=" ", flush=True)
    col, bm25_data = load_indexes()
    print("ready.")

    if args.question:
        run(args.question, col, bm25_data, args.top)
    else:
        print("UN Staff Regulations & Rules — search index")
        print('Type a question or "quit" to exit.\n')
        while True:
            try:
                q = input("? ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not q or q.lower() in ("quit", "exit", "q"):
                break
            run(q, col, bm25_data, args.top)


if __name__ == "__main__":
    main()
