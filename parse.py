"""
Parse un2018.pdf (UN Staff Regulations and Rules) into
organized markdown files.
"""
import re
import os
from pathlib import Path
from pypdf import PdfReader

# ── helpers ──────────────────────────────────────────────────

ROMAN = {
    'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5,
    'VI': 6, 'VII': 7, 'VIII': 8, 'IX': 9, 'X': 10,
    'XI': 11, 'XII': 12, 'XIII': 13,
}


def roman_to_int(s):
    return ROMAN.get(s.strip(), 0)


def slugify(s):
    s = s.lower().strip()
    s = re.sub(r'[^a-z0-9]+', '-', s)
    return s.strip('-')


def fix_pdf_artifacts(text):
    """Fix common pypdf extraction artifacts in body text."""
    # "word -hyphen" → "word-hyphen"
    text = re.sub(r'(\w) -(\w)', r'\1-\2', text)
    # "syl-\nlable" → "syllable" (hyphenated line breaks)
    text = re.sub(r'-\s*\n\s*', '', text)
    return text


# Suffixes/fragments that never begin an English word — safe to rejoin
_SUFFIX_RE = re.compile(
    r'([a-z]) '
    r'(iplinary|zation|ation|ntment|ignment|tion|sion|ness|ence|ance'
    r'|ff(?=[a-z\-])|ns\b|ent(?=\b))',
    re.I,
)


def fix_title(s):
    """Fix PDF text extraction artifacts in a section title."""
    s = re.sub(r'(\w) -(\w)', r'\1-\2', s)   # "Settling -in" → "Settling-in"
    s = re.sub(r' {2,}', ' ', s)              # collapse double spaces
    s = _SUFFIX_RE.sub(r'\1\2', s)            # rejoin suffix fragments
    return s.strip()


def clean_page(text):
    """Remove page headers/footers."""
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        if re.match(r'^\s*ST/SGB/\d+/\d+\s*$', line):
            continue
        if re.match(r'^\s*\d+/120\s+18-\d+\s*$', line):
            continue
        if re.match(r'^\s*18-\d+\s+\d+/120\s*$', line):
            continue
        cleaned.append(line)
    return '\n'.join(cleaned)


def extract_pages(pdf_path):
    reader = PdfReader(pdf_path)
    pages = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ''
        text = clean_page(text)
        pages.append((i + 1, text))
    return pages


def full_text_with_markers(pages):
    parts = []
    for num, text in pages:
        parts.append(f'\n===PAGE {num}===\n{text}')
    return '\n'.join(parts)


# ── section detection ─────────────────────────────────────────

RE_ARTICLE    = re.compile(r'^\s{1,4}(Article\s+(I{1,4}V?|V?I{0,3}X?|X{1,3}I{0,3}|XIII))\s*$', re.M)
RE_CHAPTER    = re.compile(r'^\s{1,4}(Chapter\s+(I{1,4}V?|V?I{0,3}X?|X{1,3}I{0,3}|XIII))\s*$', re.M)
# Handle PDF artifacts: "Regulat ion 2.1" and "Regulation 3. 1"
RE_REGULATION = re.compile(r'^\s{1,4}(Regulat\s*ion\s+(\d+\.?\s*\d+))\s*$', re.M)
RE_RULE       = re.compile(r'^\s{1,4}(Rule\s+(\d+\.?\s*\d+))\s*$', re.M)
RE_ANNEX      = re.compile(r'^(Annex\s+(I{1,4}V?|V?I{0,3}X?))\s*$', re.M)
RE_APPENDIX   = re.compile(r'^(Appendix\s+([A-D]))\s*$', re.M)
RE_PAGE       = re.compile(r'===PAGE (\d+)===')
RE_SCOPE      = re.compile(r'^\s{1,4}Scope and purpose\s*$', re.M)

CHAPTER_TITLES = {
    1:  'Duties, Obligations and Privileges',
    2:  'Classification of Posts and Staff',
    3:  'Salaries and Related Allowances',
    4:  'Appointment and Promotion',
    5:  'Annual and Special Leave',
    6:  'Social Security',
    7:  'Travel and Relocation Expenses',
    8:  'Staff Relations',
    9:  'Separation from Service',
    10: 'Disciplinary Measures',
    11: 'Appeals',
    12: 'General Provisions',
    13: 'Transitional Measures',
}


def current_page(text_so_far):
    matches = list(RE_PAGE.finditer(text_so_far))
    return int(matches[-1].group(1)) if matches else 1


def title_after_heading(body_raw, match_end_in_body):
    """Return the first non-blank line after the heading, with line-break hyphens joined."""
    nl = body_raw.find('\n', match_end_in_body)
    if nl == -1:
        return ''
    # Apply hyphen line-join fix on a small window so broken titles are reunited
    window = re.sub(r'-\s*\n\s*', '', body_raw[nl:nl + 300])
    for line in window.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ''


def clean_body(text):
    """Clean a section body for markdown output."""
    text = RE_PAGE.sub('', text)
    # Fix PDF hyphen artifacts
    text = re.sub(r'(\w) -(\w)', r'\1-\2', text)
    text = re.sub(r'-\s*\n\s*', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    lines = [l.rstrip() for l in text.splitlines()]
    return '\n'.join(lines).strip()


def strip_heading_repeat(body, heading_label, title):
    """Remove the heading line(s) that repeat at the top of body."""
    lines = body.splitlines()
    skip = {heading_label.strip(), title.strip()}
    out = []
    skipping = True
    for line in lines:
        if skipping and line.strip() in skip:
            continue
        skipping = False
        out.append(line)
    return '\n'.join(out).strip()


# ── splitting logic ───────────────────────────────────────────

def find_splits(full):
    splits = []

    for m in RE_SCOPE.finditer(full):
        pg = current_page(full[:m.start()])
        splits.append((m.start(), 'scope', 'Scope and Purpose', None, pg, m.end()))

    for m in RE_ARTICLE.finditer(full):
        n = roman_to_int(m.group(2))
        pg = current_page(full[:m.start()])
        splits.append((m.start(), 'article', m.group(1), n, pg, m.end()))

    for m in RE_CHAPTER.finditer(full):
        n = roman_to_int(m.group(2))
        pg = current_page(full[:m.start()])
        splits.append((m.start(), 'chapter', m.group(1), n, pg, m.end()))

    for m in RE_REGULATION.finditer(full):
        pg = current_page(full[:m.start()])
        splits.append((m.start(), 'regulation', m.group(1), m.group(2), pg, m.end()))

    for m in RE_RULE.finditer(full):
        pg = current_page(full[:m.start()])
        splits.append((m.start(), 'rule', m.group(1), m.group(2), pg, m.end()))

    for m in RE_ANNEX.finditer(full):
        n = roman_to_int(m.group(2))
        pg = current_page(full[:m.start()])
        splits.append((m.start(), 'annex', m.group(1), n, pg, m.end()))

    for m in RE_APPENDIX.finditer(full):
        pg = current_page(full[:m.start()])
        splits.append((m.start(), 'appendix', m.group(1), m.group(2), pg, m.end()))

    splits.sort(key=lambda x: x[0])
    return splits


# ── markdown generation ───────────────────────────────────────

def make_ref(page):
    return f'> Source: `un2018.pdf`, p. {page}\n\n'


def chapter_dir(n):
    title = CHAPTER_TITLES.get(n, f'Chapter {n}')
    return f'chapter-{n:02d}-{slugify(title)}'


def write_file(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')
    print(f'  wrote {path.relative_to(path.parents[2])}')


def build_docs(pdf_path, out_dir):
    out_dir = Path(out_dir)
    pages = extract_pages(pdf_path)
    full = full_text_with_markers(pages)

    splits = find_splits(full)
    print(f'Found {len(splits)} sections')

    sections = []
    for i, (pos, kind, label, number, pg, mend) in enumerate(splits):
        end = splits[i + 1][0] if i + 1 < len(splits) else len(full)
        body_raw = full[pos:end]
        title_line = fix_title(title_after_heading(body_raw, mend - pos))
        sections.append((kind, label, number, pg, body_raw, mend - pos, title_line))

    for kind, label, number, pg, body_raw, heading_end, title_line in sections:
        body = clean_body(body_raw)
        body = strip_heading_repeat(body, label, title_line)
        ref = make_ref(pg)

        if kind == 'scope':
            md = f'# Scope and Purpose\n\n{ref}{body}\n'
            write_file(out_dir / 'scope-and-purpose.md', md)

        elif kind in ('article', 'chapter'):
            ch_n = number
            ch_dir = out_dir / chapter_dir(ch_n)
            ch_title = CHAPTER_TITLES.get(ch_n, label)
            kind_word = 'Regulations' if kind == 'article' else 'Rules'
            readme = 'README.md' if not (ch_dir / 'README.md').exists() else 'README-rules.md'
            md = f'# {label}: {ch_title}\n\n{ref}## {kind_word}\n\n{body}\n'
            write_file(ch_dir / readme, md)

        elif kind == 'regulation':
            # Normalize number: "3. 1" → "3.1"
            num_norm = re.sub(r'\s', '', number)
            ch_n = int(num_norm.split('.')[0])
            ch_dir = out_dir / chapter_dir(ch_n)
            num_slug = num_norm.replace('.', '-')
            # Only use title_line if it looks like a real title (not body text)
            is_title = title_line and not re.match(r'^[\(\[]|^[a-z]|\d\.', title_line)
            if is_title:
                title_slug = '-' + slugify(title_line)[:70]
                h1 = f'# Regulation {num_norm}: {title_line}'
            else:
                title_slug = ''
                h1 = f'# Regulation {num_norm}'
            fname = f'regulation-{num_slug}{title_slug}.md'
            md = f'{h1}\n\n{ref}{body}\n'
            write_file(ch_dir / fname, md)

        elif kind == 'rule':
            num_norm = re.sub(r'\s', '', number)
            ch_n = int(num_norm.split('.')[0])
            ch_dir = out_dir / chapter_dir(ch_n)
            num_slug = num_norm.replace('.', '-')
            is_title = title_line and not re.match(r'^[\(\[]|^[a-z]|\d\.', title_line)
            if is_title:
                title_slug = '-' + slugify(title_line)[:70]
                h1 = f'# Rule {num_norm}: {title_line}'
            else:
                title_slug = ''
                h1 = f'# Rule {num_norm}'
            fname = f'rule-{num_slug}{title_slug}.md'
            md = f'{h1}\n\n{ref}{body}\n'
            write_file(ch_dir / fname, md)

        elif kind == 'annex':
            # label = "Annex I", number = int
            roman_part = label.split()[-1]  # "I", "II", etc.
            title_slug = slugify(title_line)[:60]
            fname = f'annex-{roman_part.lower()}-{title_slug}.md'
            md = f'# {label}: {title_line}\n\n{ref}{body}\n'
            write_file(out_dir / 'annexes' / fname, md)

        elif kind == 'appendix':
            # label = "Appendix A", number = "A"
            letter = str(number).lower()
            title_slug = slugify(title_line)[:60]
            fname = f'appendix-{letter}-{title_slug}.md'
            md = f'# {label}: {title_line}\n\n{ref}{body}\n'
            write_file(out_dir / 'appendices' / fname, md)

    print(f'\nDone. Output in {out_dir}')


if __name__ == '__main__':
    import shutil
    out = Path('/home/sprite/p/un/docs')
    if out.exists():
        shutil.rmtree(out)
    build_docs('/home/sprite/p/un/un2018.pdf', out)
