# SPDX-License-Identifier: GPL-3.0-or-later
"""Make the release copy of the source tree: every comment and docstring removed, behaviour provably unchanged.

    python tools/strip_comments.py build SRC DST        write the stripped copy of SRC into DST
    python tools/strip_comments.py verify SRC DST       prove DST is SRC without its comments (exit code 1 otherwise)

Python files (*.py, *.spec): comments come from the tokenizer, docstrings from the syntax tree, so a ``#`` or a quote inside
a string is never touched. What is kept: the shebang and the encoding declaration. A function or class whose body was only
a docstring gets ``pass``. verify parses both trees and compares them node by node (docstrings aside), so any edit that
changed the program - not only its comments - is reported.

Inno Setup scripts (*.iss), batch files (*.bat) and workflow files (*.yml): comment lines and trailing comments are removed
with a small scanner that knows strings; verify checks that every remaining line is the start of an original line and that
every removed piece was a comment.
"""
from __future__ import annotations

import ast
import io
import re
import shutil
import sys
import tokenize
from pathlib import Path

SKIP_DIRS = {"__pycache__", ".pytest_cache", ".git", "dist", "build", "installer_output", "qa_output", ".mypy_cache"}
PY_EXT = {".py", ".spec"}
CODING = re.compile(r"^[ \t\f]*#.*?coding[:=][ \t]*([-\w.]+)")
QSS_COMMENT = re.compile(r"^/\*.*?\*/\n", re.S | re.M)
QSS_ANY = re.compile(r"/\*.*?\*/\n?", re.S)
MAX_BLANK = 2
LINE = re.compile(r"[^\r\n]*(?:\r\n|\n|\r)|[^\r\n]+")


def _split(src: str) -> list[str]:
    """Lines the way the Python tokenizer counts them (str.splitlines also breaks on form feeds and U+2028)."""
    return LINE.findall(src)


class Unsupported(Exception):
    pass


# --------------------------------------------------------------------------------------------------------- python ---
def _doc_nodes(tree: ast.AST) -> list[ast.Expr]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                out.append((node, body[0]))
    return out


def _string_lines(tree: ast.AST) -> set[int]:
    """Line numbers (1-based) that sit inside a multi-line string literal: their content is data, never to be touched."""
    inside: set[int] = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Constant, ast.JoinedStr)) and getattr(n, "end_lineno", None) and n.end_lineno > n.lineno:
            if isinstance(n, ast.Constant) and not isinstance(n.value, (str, bytes)):
                continue
            inside.update(range(n.lineno + 1, n.end_lineno + 1))
    return inside


def strip_python(src: str, rel: str = "") -> str:
    tree = ast.parse(src)
    lines = _split(src)
    if not lines:
        return src
    eol = "\r\n" if lines[0].endswith("\r\n") else "\n"

    drop: set[int] = set()
    pass_at: dict[int, str] = {}
    for node, doc in _doc_nodes(tree):
        first, last = doc.lineno, doc.end_lineno
        seg = "".join(lines[first - 1:last])
        head = lines[first - 1][:doc.col_offset]
        if head.strip():
            raise Unsupported(f"{rel}:{first}: docstring shares its line with code")
        tail = lines[last - 1][doc.end_col_offset:].strip()
        if tail and not tail.startswith("#"):
            raise Unsupported(f"{rel}:{last}: code after a docstring on the same line")
        drop.update(range(first, last + 1))
        if len(node.body) == 1:
            pass_at[first] = head
        del seg

    inside = _string_lines(tree)
    trunc: dict[int, int] = {}
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type != tokenize.COMMENT:
            continue
        row, col = tok.start
        if row <= 2 and (row == 1 and tok.string.startswith("#!") or CODING.match(lines[row - 1])):
            continue
        if row in drop:
            continue
        if lines[row - 1][:col].strip() == "":
            drop.add(row)
        else:
            trunc[row] = col

    out: list[str] = []
    for i, line in enumerate(lines, 1):
        if i in pass_at:
            out.append(pass_at[i] + "pass" + eol)
            continue
        if i in drop:
            continue
        if i in trunc:
            line = line[:trunc[i]].rstrip() + (eol if line.endswith(("\n", "\r")) else "")
        out.append(line)

    # blank runs left behind by removed lines; lines inside a string are data and stay as they are
    kept_index = [i for i, line in enumerate(lines, 1) if i in pass_at or (i not in drop)]
    res: list[str] = []
    blanks = 0
    for ln, line in zip(kept_index, out):
        if ln not in inside and line.strip() == "":
            blanks += 1
            if blanks > MAX_BLANK:
                continue
        else:
            blanks = 0
        res.append(line)
    while res and res[0].strip() == "":
        res.pop(0)
    while res and res[-1].strip() == "":
        res.pop()
    text = "".join(res)
    if text and not text.endswith(("\n", "\r")):
        text += eol
    if rel.replace("\\", "/").endswith("ui/theme.py"):
        text = QSS_COMMENT.sub("", text)
    ast.parse(text)
    return text


def _normal(tree: ast.AST) -> ast.AST:
    """The tree without docstrings (a body left empty gets ``pass``) and without /* */ text inside string constants."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            b = node.body
            if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant) and isinstance(b[0].value.value, str):
                del b[0]
                if not b:
                    b.append(ast.Pass())
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and "/*" in node.value:
            node.value = QSS_ANY.sub("", node.value)
    return tree


def verify_python(orig: str, new: str, rel: str) -> list[str]:
    problems: list[str] = []
    a = ast.dump(_normal(ast.parse(orig)))
    b = ast.dump(_normal(ast.parse(new)))
    if a != b:
        problems.append(f"{rel}: syntax tree differs from the original")
    tree = ast.parse(new)
    if _doc_nodes(tree):
        problems.append(f"{rel}: a docstring is still there")
    nlines = _split(new)
    for tok in tokenize.generate_tokens(io.StringIO(new).readline):
        if tok.type == tokenize.COMMENT:
            row = tok.start[0]
            if not (row <= 2 and (tok.string.startswith("#!") or CODING.match(nlines[row - 1]))):
                problems.append(f"{rel}:{row}: comment left: {tok.string[:40]}")
    return problems


# ------------------------------------------------------------------------------------------------------ inno setup ---
def _pascal_strip(line: str, state: dict) -> str:
    """Remove // and { } and (* *) comments from one line of Pascal Script; 'strings' are respected."""
    out = []
    i, n = 0, len(line)
    while i < n:
        ch = line[i]
        if state["block"]:
            end = "}" if state["block"] == "{" else "*)"
            j = line.find(end, i)
            if j < 0:
                return "".join(out)
            i = j + len(end)
            state["block"] = None
            continue
        if ch == "'":
            j = i + 1
            while j < n:
                if line[j] == "'":
                    if j + 1 < n and line[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            out.append(line[i:j + 1])
            i = j + 1
            continue
        if line.startswith("//", i):
            break
        if ch == "{":
            state["block"] = "{"
            i += 1
            continue
        if line.startswith("(*", i):
            state["block"] = "(*"
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def strip_inno(src: str) -> str:
    eol = "\r\n" if "\r\n" in src else "\n"
    in_code = False
    state = {"block": None}
    res: list[str] = []
    for raw in src.splitlines():
        s = raw.strip()
        if s.startswith("[") and s.endswith("]") and state["block"] is None:
            in_code = s.lower() == "[code]"
            res.append(raw)
            continue
        if in_code:
            new = _pascal_strip(raw, state).rstrip()
            if new.strip() == "" and raw.strip() != "":
                continue
            res.append(new)
        else:
            if s.startswith(";"):
                continue
            res.append(raw)
    return _squeeze(res, eol, 1)


def verify_inno(orig: str, new: str, rel: str) -> list[str]:
    return _verify_lines(orig, new, rel, _inno_whole, _inno_tail)


def _inno_whole(line: str, in_code: bool) -> bool:
    s = line.strip()
    return s.startswith(";") if not in_code else s.startswith(("//", "{", "(*"))


def _inno_tail(rest: str, in_code: bool) -> bool:
    r = rest.lstrip()
    return in_code and r.startswith(("//", "{", "(*"))


# ------------------------------------------------------------------------------------------------- batch / yaml ---
BAT_COMMENT = re.compile(r"^\s*(@?rem(\s|$)|::)", re.I)


def strip_bat(src: str) -> str:
    eol = "\r\n" if "\r\n" in src else "\n"
    kept = [ln for ln in src.splitlines() if not BAT_COMMENT.match(ln)]
    return _squeeze(kept, eol, 1)


def strip_yaml(src: str) -> str:
    eol = "\r\n" if "\r\n" in src else "\n"
    kept = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
    for ln in kept:
        if re.search(r"\s#\s", ln):
            raise Unsupported("a trailing # in a yaml line: check by hand: " + ln)
    return _squeeze(kept, eol, 1)


def _squeeze(lines: list[str], eol: str, max_blank: int) -> str:
    res: list[str] = []
    blanks = 0
    for ln in lines:
        if ln.strip() == "":
            blanks += 1
            if blanks > max_blank:
                continue
        else:
            blanks = 0
        res.append(ln)
    while res and res[0].strip() == "":
        res.pop(0)
    while res and res[-1].strip() == "":
        res.pop()
    return eol.join(res) + eol


def _verify_lines(orig: str, new: str, rel: str, whole, tail) -> list[str]:
    """Walk the original line by line: each one is either the next line of the new file, the start of it (a trailing comment
    was cut) or a removed line - blank or a whole-line comment. Nothing else may be missing or added."""
    problems: list[str] = []
    ol, nl = orig.splitlines(), new.splitlines()
    j = 0
    in_code = False
    for i, line in enumerate(ol):
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            in_code = s.lower() == "[code]"
        if j < len(nl) and nl[j] == line:
            j += 1
        elif j < len(nl) and nl[j].strip() and line.startswith(nl[j]) and tail(line[len(nl[j]):], in_code):
            j += 1
        elif s == "" or whole(line, in_code):
            continue
        else:
            problems.append(f"{rel}:{i + 1}: a line disappeared that is not a comment: {line[:60]}")
    if j != len(nl):
        problems.append(f"{rel}: the new file has lines that are not in the original (from line {j + 1})")
    return problems


def verify_simple(orig: str, new: str, rel: str) -> list[str]:
    def whole(line: str, _code: bool) -> bool:
        s = line.strip()
        return bool(BAT_COMMENT.match(line)) if rel.endswith(".bat") else s.startswith("#")
    return _verify_lines(orig, new, rel, whole, lambda rest, code: False)


# --------------------------------------------------------------------------------------------------------- driver ---
def _read(p: Path) -> str:
    with open(p, encoding="utf-8", newline="") as fh:
        return fh.read()


def _strip_one(path: Path, text: str, rel: str) -> str | None:
    ext = path.suffix.lower()
    if ext in PY_EXT:
        return strip_python(text, rel)
    if ext == ".iss":
        return strip_inno(text)
    if ext == ".bat":
        return strip_bat(text)
    if ext in (".yml", ".yaml"):
        return strip_yaml(text)
    return None


def build(src: Path, dst: Path) -> int:
    if dst.exists():
        shutil.rmtree(dst)
    count = {"stripped": 0, "copied": 0}
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        if any(part in SKIP_DIRS for part in rel.parts) or p.suffix == ".pyc":
            continue
        out = dst / rel
        if p.is_dir():
            out.mkdir(parents=True, exist_ok=True)
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            text = _read(p) if p.suffix.lower() in PY_EXT | {".iss", ".bat", ".yml", ".yaml"} else None
        except UnicodeDecodeError:
            text = None
        new = _strip_one(p, text, rel.as_posix()) if text is not None else None
        if new is None:
            shutil.copy2(p, out)
            count["copied"] += 1
        else:
            with open(out, "w", encoding="utf-8", newline="") as fh:
                fh.write(new)
            shutil.copystat(p, out)
            count["stripped"] += 1
    print(f"stripped {count['stripped']} files, copied {count['copied']} unchanged -> {dst}")
    return 0


def verify(src: Path, dst: Path) -> int:
    problems: list[str] = []
    checked = 0
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        if p.is_dir() or any(part in SKIP_DIRS for part in rel.parts) or p.suffix == ".pyc":
            continue
        q = dst / rel
        if not q.exists():
            problems.append(f"{rel}: missing in the release copy")
            continue
        ext = p.suffix.lower()
        if ext in PY_EXT:
            problems += verify_python(_read(p), _read(q), rel.as_posix())
        elif ext == ".iss":
            problems += verify_inno(_read(p), _read(q), rel.as_posix())
        elif ext in (".bat", ".yml", ".yaml"):
            problems += verify_simple(_read(p), _read(q), rel.as_posix())
        else:
            if p.read_bytes() != q.read_bytes():
                problems.append(f"{rel}: a file that should be identical differs")
        checked += 1
    for q in sorted(dst.rglob("*")):
        if q.is_file() and not (src / q.relative_to(dst)).exists():
            problems.append(f"{q.relative_to(dst)}: not in the source")
    for line in problems:
        print("PROBLEM", line)
    print(f"verified {checked} files: {'OK' if not problems else str(len(problems)) + ' problem(s)'}")
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    if len(argv) != 4 or argv[1] not in ("build", "verify"):
        print(__doc__)
        return 2
    src, dst = Path(argv[2]), Path(argv[3])
    return build(src, dst) if argv[1] == "build" else verify(src, dst)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
