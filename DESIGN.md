# UN Staff Regulations & Rules — Knowledge Base

Source document: `un2018.pdf`
(ST/SGB/2018/1, 120 pages)

## Overview

The PDF is parsed into a structured set of Markdown
files organized by chapter, regulation, and rule.
A hybrid search index is built over those files to
support fast, accurate question answering.

```
un2018.pdf
    │
    ▼  parse.py
docs/
    scope-and-purpose.md
    chapter-01-duties-obligations-and-privileges/
        README.md               ← regulations overview
        README-rules.md         ← rules overview
        regulation-1-1-status-of-staff.md
        rule-1-1-status-of-staff.md
        …
    chapter-02-…/ … chapter-13-…/
    annexes/
        annex-i-salary-scales-and-related-provisions.md
        …
    appendices/
        appendix-a-pensionable-remuneration.md
        …
    │
    ▼  index.py
.index/
    chroma/     ← persistent ChromaDB vector store
    bm25.pkl    ← BM25 keyword index + metadata
    │
    ▼  query.py
interactive search CLI
```

---

## PDF-to-Markdown Pipeline (`parse.py`)

### Tools

| Package | Version | Purpose |
|---------|---------|---------|
| `pypdf` | latest  | PDF text extraction |
| (stdlib) | —      | regex parsing, pathlib I/O |

### Extraction

`pypdf` extracts text page by page. Each page is
wrapped with a `===PAGE N===` sentinel so page
numbers are tracked throughout the text stream.
Page headers and footers (document reference numbers
and page-count stamps) are stripped at this stage.

### Parsing strategy

No PDF outline/bookmarks exist in this document,
so structure is detected entirely from the text.
Six heading patterns are matched with regexes:

| Pattern | Example | Maps to |
|---------|---------|---------|
| `Article [Roman]` | `Article I` | Chapter (Regulations) |
| `Chapter [Roman]` | `Chapter I` | Chapter (Rules) |
| `Regulation N.N` | `Regulation 1.2` | Individual regulation |
| `Rule N.N` | `Rule 6.2` | Individual rule |
| `Annex [Roman]` | `Annex I` | Annex |
| `Appendix [A-D]` | `Appendix A` | Appendix |

The full text stream is split at every match.
The body of each section runs from its heading
to the start of the next heading.

### PDF artifact cleanup

The PDF renderer introduces several text artifacts
that are cleaned before output:

- **Line-break hyphens** — `authori-\nzation` is
  rejoined into `authorization`. Applied in both
  body text and title extraction.

- **Spaced compound words** — `Secretary -General`
  (space before hyphen) is collapsed to
  `Secretary-General`.

- **Suffix fragments** — mid-word spaces where the
  second token is a recognized English suffix that
  can never start a word (`tion`, `zation`, `ment`,
  `iplinary`, `ence`, `ance`, `ness`, `ff`, `ns`,
  `ent`) are joined: `Authori zation` →
  `Authorization`, `disc iplinary` →
  `disciplinary`.

- **Spaced regulation numbers** — `3. 1` and
  `Regulat ion 2.1` are normalized to `3.1` /
  `Regulation 2.1` so the heading regex matches.

Artifact cleanup is applied to the **title line**
(used for the H1 heading and file name) via
`fix_title()`. Body text receives only the
line-break-hyphen fix; residual mid-word spaces
in the body are a known limitation of the PDF
text layer and do not affect navigation or search.

### Output format

Each Markdown file follows this structure:

```markdown
# [Type] [Number]: [Title]

> Source: `un2018.pdf`, p. N

[body text]
```

The source reference on every file ties the content
back to its exact page in the original PDF.

Regulations with no separate title line (chapters
III–XIII) use the heading alone (`# Regulation 3.2`)
rather than a body-derived slug.

### Directory layout

```
docs/
  scope-and-purpose.md
  chapter-NN-<slug>/
    README.md          ← Article (Regulations block)
    README-rules.md    ← Chapter (Rules block)
    regulation-N-N[-title].md
    rule-N-N-title.md
  annexes/
    annex-<roman>-<title>.md
  appendices/
    appendix-<letter>-<title>.md
```

Chapter directories are zero-padded (`chapter-01`,
`chapter-02`, …) so they sort correctly.

---

## Indexing (`index.py`)

### Tools

| Package | Purpose |
|---------|---------|
| `chromadb` | Persistent vector store |
| `rank_bm25` | BM25Okapi keyword index |
| `all-MiniLM-L6-v2` (ONNX) | Embedding model bundled with ChromaDB |

### What is indexed

Every `.md` file under `docs/` is one document.
For each document the following metadata is stored:

| Field | Description |
|-------|-------------|
| `title` | H1 heading |
| `kind` | `regulation`, `rule`, `annex`, `appendix`, `chapter-overview` |
| `number` | e.g. `6.2`, `13.1` |
| `chapter` | integer chapter number |
| `section` | parent directory name |
| `page` | PDF page from the source line |
| `path` | absolute path to the `.md` file |

The **vector index** (ChromaDB) embeds the title +
stripped body text using the bundled ONNX
`all-MiniLM-L6-v2` model (384-dimensional dense
vectors, cosine distance). The model is downloaded
once (~80 MB) and cached in
`~/.cache/chroma/onnx_models/`.

The **BM25 index** (`rank_bm25.BM25Okapi`) indexes
the same text tokenized to lowercase words.
It is serialized to `.index/bm25.pkl` alongside
the document metadata and body text.

### Running

```bash
python3 index.py
```

Re-running is safe — the ChromaDB collection is
dropped and recreated, and `bm25.pkl` is
overwritten. Run again whenever `docs/` changes.

---

## Querying (`query.py`)

### Hybrid retrieval

Each query runs two retrievals in parallel:

1. **BM25** — scores all 185 documents and
   normalizes scores to `[0, 1]` by dividing by
   the maximum BM25 score.

2. **Vector** — retrieves the top `3×k` nearest
   neighbours from ChromaDB (cosine distance)
   and converts distances to similarities by
   normalizing to `[0, 1]`.

The final score is:

```
score = 0.5 × bm25_norm + 0.5 × vec_sim
```

The top `k` documents (default 5) are returned
ranked by combined score.

Hybrid retrieval improves on either method alone:
BM25 catches exact legal terms (`termination
indemnity`, `Rule 9.8`) while the vector index
handles paraphrased or conceptual queries
(`"what happens when staff retire"` → Rule 9.5).

### Usage

```bash
# one-shot query
python3 query.py "sick leave entitlement"

# show more results
python3 query.py --top 8 "disciplinary procedures"

# interactive REPL (Ctrl-D or type "quit" to exit)
python3 query.py
```

Each result displays:

- Rank, document type, and title
- Source PDF page number and hybrid score
- Regulation/rule number and chapter section
- First ~600 characters of body text

To read the full text, open the file shown in the
`Section` field under `docs/`.

### Extending with an LLM

The query script is intentionally output-only.
To get a synthesized answer, pipe the top results
to Claude:

```bash
python3 query.py "annual leave accrual rate" \
  | claude --print "Answer the question based on the
    context above. Cite regulation numbers."
```

Or ask me (Claude Code) directly — I can run
`query.py` and read the full source files to give
a cited answer.
