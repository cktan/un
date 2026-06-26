"""
Build a hybrid BM25 + vector index over docs/*.

Run once:
  python3 index.py

Produces:
  .index/chroma/   — persistent ChromaDB vector store
  .index/bm25.pkl  — BM25 keyword index + metadata
"""
import re
import pickle
import pathlib
from rank_bm25 import BM25Okapi
import chromadb

DOCS_DIR = pathlib.Path(__file__).parent / "docs"
INDEX_DIR = pathlib.Path(__file__).parent / ".index"


# ── metadata extraction ───────────────────────────────────────

def parse_md(path: pathlib.Path) -> dict:
    text = path.read_text()
    lines = text.splitlines()

    # H1 title
    title = next((l.lstrip("# ").strip() for l in lines if l.startswith("# ")), path.stem)

    # Source page
    page_match = re.search(r'`un2018\.pdf`, p\. (\d+)', text)
    page = int(page_match.group(1)) if page_match else 0

    # Derive type and number from filename
    name = path.stem
    if name.startswith("regulation-"):
        kind = "regulation"
        num = re.match(r'regulation-(\d+-\d+)', name)
        number = num.group(1).replace("-", ".") if num else ""
    elif name.startswith("rule-"):
        kind = "rule"
        num = re.match(r'rule-(\d+-\d+)', name)
        number = num.group(1).replace("-", ".") if num else ""
    elif name.startswith("annex-"):
        kind = "annex"
        number = ""
    elif name.startswith("appendix-"):
        kind = "appendix"
        number = ""
    elif name in ("README", "README-rules"):
        kind = "chapter-overview"
        number = ""
    else:
        kind = "other"
        number = ""

    # Chapter from parent dir name
    parent = path.parent.name
    ch_match = re.match(r'chapter-(\d+)', parent)
    chapter = int(ch_match.group(1)) if ch_match else 0

    # Strip markdown syntax for plain-text body
    body = re.sub(r'^#+\s+.*$', '', text, flags=re.M)   # headings
    body = re.sub(r'^>.*$', '', body, flags=re.M)         # blockquotes (source refs)
    body = re.sub(r'\s+', ' ', body).strip()

    return {
        "id": str(path.relative_to(DOCS_DIR)),
        "path": str(path),
        "title": title,
        "body": body,
        "page": page,
        "kind": kind,
        "number": number,
        "chapter": chapter,
        "section": parent,
    }


# ── build indexes ─────────────────────────────────────────────

def build():
    INDEX_DIR.mkdir(exist_ok=True)

    docs = [parse_md(p) for p in sorted(DOCS_DIR.rglob("*.md"))]
    print(f"Parsed {len(docs)} documents")

    # ── ChromaDB vector index ─────────────────────────────────
    chroma_path = str(INDEX_DIR / "chroma")
    client = chromadb.PersistentClient(path=chroma_path)

    # Drop and recreate so re-running index.py is idempotent
    try:
        client.delete_collection("un2018")
    except Exception:
        pass
    col = client.create_collection("un2018")

    BATCH = 50
    for i in range(0, len(docs), BATCH):
        batch = docs[i:i + BATCH]
        col.add(
            ids=[d["id"] for d in batch],
            documents=[f"{d['title']}\n\n{d['body']}" for d in batch],
            metadatas=[{
                "title":   d["title"],
                "kind":    d["kind"],
                "number":  d["number"],
                "chapter": d["chapter"],
                "section": d["section"],
                "page":    d["page"],
                "path":    d["path"],
            } for d in batch],
        )
        print(f"  vector: indexed {min(i+BATCH, len(docs))}/{len(docs)}")

    # ── BM25 keyword index ────────────────────────────────────
    tokenize = lambda s: re.findall(r'\w+', s.lower())
    corpus = [tokenize(f"{d['title']} {d['body']}") for d in docs]
    bm25 = BM25Okapi(corpus)

    bm25_data = {
        "bm25": bm25,
        "docs": [{k: v for k, v in d.items() if k != "body"} for d in docs],
        "bodies": [d["body"] for d in docs],
    }
    with open(INDEX_DIR / "bm25.pkl", "wb") as f:
        pickle.dump(bm25_data, f)
    print(f"  bm25:   indexed {len(docs)} documents")

    print(f"\nDone. Index saved to {INDEX_DIR}/")


if __name__ == "__main__":
    build()
