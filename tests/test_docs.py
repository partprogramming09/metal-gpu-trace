"""The release rule: a version from 0.26.0 on ships 1 to 5 improvements, each one a CHANGELOG bullet under
"### Added" that starts with its icon and ends with a link to its proof in docs/evidence/, and both READMEs link each
proof from their "What's new" section. Experimental (🧪) bullets need their proof too but do not count toward the
minimum. Older sections keep their own format and are not checked."""
import ast
import json
import re

from support import ROOT

FIRST_CHECKED = (0, 26, 0)
MIN_IMPROVEMENTS, MAX_IMPROVEMENTS = 0, 10**9  # no limit: `lanzamientos: continuo` in CLAUDE.md (a test pins both)
ICONS = "✨🔍🩺⚡🛡⚠🧪🛠"  # the icon vocabulary of docs/evidence/README.md, without variation selectors
EXPERIMENTAL = "🧪"
PROOF = re.compile(r"\[(?:proof|prueba)\]\((docs/evidence/v(\d+\.\d+\.\d+)\.md)#([\w-]+)\)\s*$")


def sections(changelog):
    """Returns [(version tuple, text)] for each `## X.Y.Z` section of the changelog, newest first as written."""
    found = []
    parts = re.split(r"(?m)^## (\d+)\.(\d+)\.(\d+)[^\n]*\n", changelog)
    for i in range(1, len(parts), 4):
        found.append(((int(parts[i]), int(parts[i + 1]), int(parts[i + 2])), parts[i + 3]))
    return found


def slug(heading):
    """GitHub's anchor for a heading: lower case, punctuation dropped, spaces to hyphens."""
    return re.sub(r"\s", "-", re.sub(r"[^\w\s-]", "", heading.strip().lower()))


def headings(markdown):
    """Returns the headings of a markdown text, leaving out lines inside fenced code blocks."""
    return re.findall(r"(?m)^#+ (.+)$", re.sub(r"(?ms)^```.*?^```", "", markdown))


def improvements(section):
    """Returns the bullets under `### Added` that start with one of the ICONS."""
    added = re.search(r"(?ms)^### Added\s*\n(.*?)(?=^### |\Z)", section)
    bullets = re.findall(r"(?ms)^- (.*?)(?=^- |\Z)", added.group(1)) if added else []
    return [" ".join(b.split()) for b in bullets if b and b[0] in ICONS]


def problems(changelog, readmes, evidence_files):
    """Returns what is wrong with the newest release: `readmes` maps a README name to its text and `evidence_files`
    maps a path such as docs/evidence/v0.26.0.md to its text. A version before FIRST_CHECKED has no problems."""
    found = sections(changelog)
    if not found or found[0][0] < FIRST_CHECKED:
        return []
    version, text = found[0]
    name = ".".join(map(str, version))
    bullets = improvements(text)
    if not bullets and re.findall(r"(?m)^### (.+)$", text) == ["Fixed"]:
        icons = [i for i in re.findall(r"(?m)^- (\S)", text) if i in ICONS]
        if icons and all(i == "🛠" for i in icons):
            return []  # a release of fixes only has no minimum or maximum
    counted = [b for b in bullets if not b.startswith(EXPERIMENTAL)]
    wrong = []
    if not MIN_IMPROVEMENTS <= len(counted) <= MAX_IMPROVEMENTS or len(bullets) > MAX_IMPROVEMENTS:
        wrong.append(f"{name} has {len(counted)} improvements ({len(bullets) - len(counted)} experimental); "
                     f"a release has {MIN_IMPROVEMENTS} to {MAX_IMPROVEMENTS}, experimental ones not counting "
                     f"toward the minimum but counting toward the maximum ({len(bullets)} bullets here)")
    anchors = []
    for bullet in bullets:
        proof = PROOF.search(bullet)
        if not proof or proof.group(2) != name:
            wrong.append(f"{bullet[:60]!r} does not end with a [proof](docs/evidence/v{name}.md#anchor) link")
        elif proof.group(1) not in evidence_files:
            wrong.append(f"{proof.group(1)} does not exist")
        elif proof.group(3) not in {slug(h) for h in headings(evidence_files[proof.group(1)])}:
            wrong.append(f"{proof.group(1)} has no heading for #{proof.group(3)}")
        else:
            anchors.append(proof.group(3))
    for readme, content in readmes.items():
        whats_new = re.search(r"(?ms)^## What's new\s*\n(.*?)(?=^## |\Z)", content)
        if not whats_new:
            wrong.append(f"{readme} has no What's new section")
            continue
        wrong.extend(f"{readme} What's new does not link v{name}.md#{a}" for a in anchors
                     if f"docs/evidence/v{name}.md#{a}" not in whats_new.group(1))
    return wrong


def good_changelog(count=5, version="0.26.0", icon="✨", section="Added"):
    bullets = "".join(f"- {icon} Thing {i}: what changes for the reader. [proof](docs/evidence/v{version}.md#thing-{i})\n"
                      for i in range(count))
    return f"# Changelog\n\n## {version} — 2026-12-01\n\n### {section}\n\n{bullets}\n## 0.25.0 — 2026-11-15\n\n- old\n"


def good_evidence(count=5):
    return "# Proof\n\n" + "".join(f"## Thing {i}\n\ncommand, real output\n\n" for i in range(count))


def readmes(count=5, prefix=("",)):
    rows = "".join(f"- [proof]({{p}}docs/evidence/v0.26.0.md#thing-{i})\n" for i in range(count))
    return {"README.md": "## What's new\n\n" + rows.format(p=prefix[0]) + "\n## Other\n"}


def evidence(count=5):
    return {"docs/evidence/v0.26.0.md": good_evidence(count)}


def test_a_complete_release_has_no_problems():
    assert problems(good_changelog(), readmes(), evidence()) == []


def test_a_release_has_no_limit_on_its_improvements():
    for count in (0, 1, 5, 12):
        assert problems(good_changelog(count), readmes(count), evidence(count)) == []
    mixed = good_changelog(5, icon="🧪")  # experimental ones are allowed in any number
    assert problems(mixed, readmes(), evidence()) == []
    plain = good_changelog(5).replace("### Added\n", "### Added\n\n- plain note, no icon\n", 1)  # not a bullet of the rule
    assert problems(plain, readmes(), evidence()) == []


def test_each_improvement_links_to_an_existing_evidence_anchor():
    no_link = good_changelog().replace(" [proof](docs/evidence/v0.26.0.md#thing-0)", "")
    assert "does not end with" in problems(no_link, readmes(), evidence())[0]
    assert "does not exist" in problems(good_changelog(), readmes(), {})[0]
    assert "no heading for #thing-4" in problems(good_changelog(), readmes(), evidence(4))[0]
    other_version = good_changelog().replace("evidence/v0.26.0.md#thing-1", "evidence/v0.25.0.md#thing-1")
    assert "does not end with" in problems(other_version, readmes(), evidence())[0]


def test_an_anchor_with_an_underscore_is_accepted():
    changelog = good_changelog().replace("#thing-0", "#capture_diff-compares")
    proofs = {"docs/evidence/v0.26.0.md": good_evidence().replace("## Thing 0", "## capture_diff compares")}
    docs = readmes()
    docs["README.md"] = docs["README.md"].replace("#thing-0", "#capture_diff-compares")
    assert problems(changelog, docs, proofs) == []


def test_a_heading_inside_a_code_block_is_not_a_heading():
    proofs = {"docs/evidence/v0.26.0.md": good_evidence(4) + "```\n## Thing 4\n```\n"}
    assert "no heading for #thing-4" in problems(good_changelog(), readmes(), proofs)[0]


def test_a_bullet_without_an_icon_is_not_an_improvement():
    plain = good_changelog(2).replace("- ✨ Thing 0", "- Thing 0").replace("- ✨ Thing 1", "- Évite Thing 1")
    assert improvements(plain) == []


def test_only_the_added_section_counts():
    assert improvements(good_changelog(section="Changed")) == []
    assert len(improvements(good_changelog())) == 5


def test_the_readme_links_every_improvement():
    missing = {"README.md": "## What's new\n"}
    assert "README.md What's new does not link v0.26.0.md#thing-0" in problems(good_changelog(), missing, evidence())
    no_section = readmes()
    no_section["README.md"] = "## Other\n"
    assert problems(good_changelog(), no_section, evidence())[0] == "README.md has no What's new section"
    one_short = readmes(4)
    assert problems(good_changelog(), one_short, evidence()) == ["README.md What's new does not link v0.26.0.md#thing-4"]


def test_old_changelog_sections_are_not_checked():
    assert problems("# Changelog\n\n## 0.25.0 — 2026-11-15\n\n- anything\n", {}, {}) == []
    assert problems("# Changelog\n", {}, {}) == []


def test_a_release_of_fixes_only_needs_no_improvements():
    assert problems("## 0.27.1 — 2026-11-16\n\n### Fixed\n\n- 🛠️ A fix.\n", {}, {}) == []


def test_the_numbers_here_match_claude_md():
    assert re.search(r"(?m)^lanzamientos: continuo$", (ROOT / "CLAUDE.md").read_text(encoding="utf-8"))
    assert (MIN_IMPROVEMENTS, MAX_IMPROVEMENTS) == (0, 10**9)


def test_the_package_version_has_its_changelog_section():
    """A version bump without its `## X.Y.Z` heading (an `## Unreleased` left in place) would skip the release rule."""
    from metal_gpu_trace import metal_trace_mcp
    version = tuple(int(n) for n in metal_trace_mcp.__version__.split("."))
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert version == sections(changelog)[0][0], f"CHANGELOG.md's newest section is not {metal_trace_mcp.__version__}"
    server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    assert server["version"] == server["packages"][0]["version"] == metal_trace_mcp.__version__


def test_the_real_latest_release_follows_the_rule():
    """The checkout's own CHANGELOG and READMEs: the rule holds from 0.26.0 on, and passes while 0.25.0 is the newest."""
    proofs = {f"docs/evidence/{p.name}": p.read_text(encoding="utf-8") for p in (ROOT / "docs" / "evidence").glob("v*.md")}
    docs = {n: (ROOT / n).read_text(encoding="utf-8") for n in ("README.md",)}
    assert problems((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), docs, proofs) == []


LINK = re.compile(r"\]\(([^)\s]+)\)")
SKIPPED_DIRS = {".git", ".claude", "node_modules", "dist", ".venv", ".vitepress"}


def broken_links(path, text, exists):
    """Returns the relative links of a markdown text that point at nothing, as GitHub resolves them (the file must be
    spelled out: `./how-it-works` works only in VitePress). `exists` says whether a path does. Code is not a link."""
    text = re.sub(r"`[^`\n]*`", "", re.sub(r"(?ms)^```.*?^```", "", text))
    wrong = []
    for link in LINK.findall(text):
        target = link.split("#")[0]
        if not target or re.match(r"[a-z][a-z0-9+.-]*:", link) or link.startswith("#"):
            continue
        resolved = (ROOT / target.lstrip("/")) if target.startswith("/") else path.parent / target
        if not exists(resolved):
            wrong.append(link)
    return wrong


def test_a_broken_link_is_found():
    here = ROOT / "docs" / "a.md"
    assert broken_links(here, "[x](./b) [y](b.md) [z](/guides/)", lambda p: p.name == "b.md") == ["./b", "/guides/"]
    assert broken_links(here, "`[x](./b)`\n```\n[y](./c)\n```\n[w](https://x.org) [v](#top)", lambda p: False) == []


def test_every_relative_link_in_the_markdown_files_works_on_github():
    wrong = {}
    for path in ROOT.rglob("*.md"):
        if SKIPPED_DIRS & set(path.relative_to(ROOT).parts):
            continue
        found = broken_links(path, path.read_text(encoding="utf-8"), lambda p: p.exists())
        if found:
            wrong[str(path.relative_to(ROOT))] = found
    assert wrong == {}


CITE = re.compile(r"(?<![\w.-])((?:[\w-]+/)*[\w-]+\.py)::(\w+(?:\.\w+)*)")


def definitions(code):
    """Returns the dotted names `code` defines: functions and classes (methods as `Class.method`) and module-level
    names assigned one at a time, also inside `if`/`try`. Imports and tuple assignments are re-exports: not defined.
    A nested function or method counts by its last name (`do_POST` for `serve.Handler.do_POST`)."""
    found = set()

    def walk(body, prefix, top):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                found.add(prefix + node.name)
                walk(node.body, prefix + node.name + ".", False)
            elif top and isinstance(node, ast.Assign):
                found.update(t.id for t in node.targets if isinstance(t, ast.Name))
            elif top and isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                found.add(node.target.id)
            elif isinstance(node, (ast.If, ast.Try)):
                walk(node.body + node.orelse + getattr(node, "finalbody", []), prefix, top)

    walk(ast.parse(code).body, "", True)
    return found


def wrong_citations(text, sources):
    """Returns the `file.py::name` citations of a markdown text whose file is unknown, ambiguous or does not define the
    name. `sources` maps a repo-relative path to its code. Code fences are read too: the guides cite inside them."""
    wrong = []
    for path, name in CITE.findall(text):
        hits = [p for p in sources if p == path or p.endswith("/" + path)]
        if len(hits) != 1 or not any(d == name or d.endswith("." + name) for d in definitions(sources[hits[0]])):
            wrong.append(f"{path}::{name}")
    return wrong


def test_a_citation_to_the_wrong_file_is_found():
    code = {
        "src/a.py": "def one():\n    pass\nLIMIT = 3\nclass K:\n    def m(self):\n        x = 1\n"
                    "        if x == 1:\n            pass\n",
        "src/b.py": "from a import one, LIMIT\nfrom a import (\n    K,\n)\nfoo, bar = 1, 2\n"
                    'def two():\n    """\n    note: 1\n    """\n',
    }
    assert wrong_citations("`a.py::one` `a.py::LIMIT` `a.py::K.m` `./a.py::K` `../src/b.py::two`", code) == []
    bad = ["a.py::two", "c.py::one", "a.py::K.gone", "a.py::x", "b.py::one", "b.py::K", "b.py::foo", "b.py::note"]
    assert wrong_citations(" ".join(f"`{c}`" for c in bad), code) == bad


def test_every_function_cited_by_name_in_the_docs_is_defined_in_its_file():
    sources = {str(p.relative_to(ROOT)): p.read_text(encoding="utf-8")
               for d in ("src", "tests", "windows") for p in (ROOT / d).rglob("*.py")}
    wrong = {}
    for path in (ROOT / "docs").rglob("*.md"):
        if SKIPPED_DIRS & set(path.relative_to(ROOT).parts):
            continue
        found = wrong_citations(path.read_text(encoding="utf-8"), sources)
        if found:
            wrong[str(path.relative_to(ROOT))] = found
    assert wrong == {}
