"""The release rule: a version from 0.26.0 on ships 1 to 5 improvements, each one a CHANGELOG bullet under
"### Added" that starts with its icon and ends with a link to its proof in docs/evidence/, and both READMEs link each
proof from their "What's new" section. Experimental (🧪) bullets need their proof too but do not count toward the
minimum. Older sections keep their own format and are not checked."""
import re

from support import ROOT

FIRST_CHECKED = (0, 26, 0)
MIN_IMPROVEMENTS, MAX_IMPROVEMENTS = 1, 5  # also written as `lanzamientos: 1-5` in CLAUDE.md (a test pins both)
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
        whats_new = re.search(r"(?ms)^## (?:What's new|Novedades)\s*\n(.*?)(?=^## |\Z)", content)
        if not whats_new:
            wrong.append(f"{readme} has no What's new / Novedades section")
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


def readmes(count=5, prefix=("", "../")):
    rows = "".join(f"- [proof]({{p}}docs/evidence/v0.26.0.md#thing-{i})\n" for i in range(count))
    return {"README.md": "## What's new\n\n" + rows.format(p=prefix[0]) + "\n## Other\n",
            "es/README.md": "## Novedades\n\n" + rows.format(p=prefix[1])}


def evidence(count=5):
    return {"docs/evidence/v0.26.0.md": good_evidence(count)}


def test_a_complete_release_has_no_problems():
    assert problems(good_changelog(), readmes(), evidence()) == []


def test_release_has_between_1_and_5_improvements():
    assert problems(good_changelog(0), readmes(0), evidence(0))[0].startswith("0.26.0 has 0")
    assert problems(good_changelog(6), readmes(6), evidence(6))[0].startswith("0.26.0 has 6")
    for count in (1, 5):
        assert problems(good_changelog(count), readmes(count), evidence(count)) == []


def test_experimental_improvements_do_not_count_toward_the_minimum():
    only_experimental = problems(good_changelog(5, icon="🧪"), readmes(), evidence())
    assert only_experimental and only_experimental[0].startswith("0.26.0 has 0 improvements (5 experimental)")
    mixed = good_changelog(5).replace("✨ Thing 4", "🧪 Thing 4")
    assert problems(mixed, readmes(), evidence()) == []
    too_many = good_changelog(6).replace("✨ Thing 5", "🧪 Thing 5")  # experimental ones count toward the maximum
    assert problems(too_many, readmes(6), evidence(6))[0].startswith("0.26.0 has 5 improvements (1 experimental)")
    assert "(6 bullets here)" in problems(too_many, readmes(6), evidence(6))[0]
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
    docs["es/README.md"] = docs["es/README.md"].replace("#thing-0", "#capture_diff-compares")
    assert problems(changelog, docs, proofs) == []


def test_a_heading_inside_a_code_block_is_not_a_heading():
    proofs = {"docs/evidence/v0.26.0.md": good_evidence(4) + "```\n## Thing 4\n```\n"}
    assert "no heading for #thing-4" in problems(good_changelog(), readmes(), proofs)[0]


def test_a_bullet_without_an_icon_is_not_an_improvement():
    plain = good_changelog(2).replace("- ✨ Thing 0", "- Thing 0").replace("- ✨ Thing 1", "- Évite Thing 1")
    assert problems(plain, readmes(2), evidence(2))[0].startswith("0.26.0 has 0")


def test_only_the_added_section_counts():
    assert problems(good_changelog(section="Changed"), readmes(), evidence())[0].startswith("0.26.0 has 0")


def test_both_readmes_link_every_improvement():
    missing = readmes()
    missing["es/README.md"] = "## Novedades\n"
    assert "es/README.md What's new does not link v0.26.0.md#thing-0" in problems(good_changelog(), missing, evidence())
    no_section = readmes()
    no_section["README.md"] = "## Other\n"
    assert problems(good_changelog(), no_section, evidence())[0] == "README.md has no What's new / Novedades section"
    one_short = readmes(4)
    assert problems(good_changelog(), one_short, evidence()) == [
        "README.md What's new does not link v0.26.0.md#thing-4",
        "es/README.md What's new does not link v0.26.0.md#thing-4"]


def test_old_changelog_sections_are_not_checked():
    assert problems("# Changelog\n\n## 0.25.0 — 2026-11-15\n\n- anything\n", {}, {}) == []
    assert problems("# Changelog\n", {}, {}) == []


def test_the_numbers_here_match_claude_md():
    line = re.search(r"(?m)^lanzamientos: (\d+)-(\d+)$", (ROOT / "CLAUDE.md").read_text(encoding="utf-8"))
    assert line and (int(line.group(1)), int(line.group(2))) == (MIN_IMPROVEMENTS, MAX_IMPROVEMENTS)


def test_the_package_version_has_its_changelog_section():
    """A version bump without its `## X.Y.Z` heading (an `## Unreleased` left in place) would skip the release rule."""
    from metal_gpu_trace import metal_trace_mcp
    version = tuple(int(n) for n in metal_trace_mcp.__version__.split("."))
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert version in [v for v, _ in sections(changelog)], f"CHANGELOG.md has no section for {metal_trace_mcp.__version__}"


def test_the_real_latest_release_follows_the_rule():
    """The checkout's own CHANGELOG and READMEs: the rule holds from 0.26.0 on, and passes while 0.25.0 is the newest."""
    proofs = {f"docs/evidence/{p.name}": p.read_text(encoding="utf-8") for p in (ROOT / "docs" / "evidence").glob("v*.md")}
    docs = {n: (ROOT / n).read_text(encoding="utf-8") for n in ("README.md", "es/README.md")}
    assert problems((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), docs, proofs) == []
