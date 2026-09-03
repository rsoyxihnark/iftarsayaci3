import os
import re
import subprocess
import sys

SOURCE = "iftar_sayaci.py"
CHANGELOG = "CHANGELOG.md"
VERSION_PATTERN = re.compile(r"^APP_VERSION\s*=\s*[\"']([^\"']+)[\"']", re.MULTILINE)
SUBJECT_PATTERN = re.compile(r"^\[\s*(no release|\d+(?:\.\d+)+)\s*\]")
UNRELEASED_PATTERN = re.compile(r"^#{1,6}\s*Unreleased\s*$", re.MULTILINE | re.IGNORECASE)
HEADING_PATTERN = re.compile(r"^#{1,6}\s")


def fail(message):
    print("::error::" + message)
    sys.exit(1)


def git(*args):
    result = subprocess.run(("git",) + args, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        fail("git " + " ".join(args) + " failed: " + result.stderr.strip())
    return result.stdout


def read_text(path):
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read().replace("\r\n", "\n").replace("\r", "\n")


def source_version():
    match = VERSION_PATTERN.search(read_text(SOURCE))
    if match is None:
        fail("APP_VERSION was not found in " + SOURCE + ".")
    return match.group(1).strip()


def changed_files():
    output = git("diff-tree", "--no-commit-id", "--name-only", "-r", "--root", "HEAD")
    return [line.strip() for line in output.splitlines() if line.strip()]


def bullet_entries(lines):
    return sorted(line[2:].strip() for line in lines if line.startswith("- ") and line[2:].strip())


def section_entries(text, version):
    heading = re.compile(r"^#{1,6}\s*v?" + re.escape(version) + r"\s*$")
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if heading.match(line):
            start = index + 1
            break
    if start is None:
        return None
    body = []
    for line in lines[start:]:
        if HEADING_PATTERN.match(line):
            break
        body.append(line)
    return bullet_entries(body)


def emit(name, value):
    destination = os.environ.get("GITHUB_OUTPUT")
    if destination:
        with open(destination, "a", encoding="utf-8") as handle:
            handle.write(name + "=" + value + "\n")
    print(name + "=" + value)


def main():
    subject = git("log", "-1", "--pretty=%s").strip()
    body = git("log", "-1", "--pretty=%b")
    files = changed_files()
    version = source_version()
    changelog_text = read_text(CHANGELOG) if os.path.exists(CHANGELOG) else ""
    changelog_touched = CHANGELOG in files

    match = SUBJECT_PATTERN.match(subject)
    if match is None:
        fail("The commit subject has to start with [" + version + "] or [no release]: " + subject)
    marker = match.group(1)

    if marker == "no release":
        if changelog_touched and UNRELEASED_PATTERN.search(changelog_text) is None:
            fail("A [no release] commit with entries puts them under an Unreleased heading.")
        emit("release", "false")
        emit("version", version)
        emit("tag", "")
        print("This commit ships nothing to users.")
        return

    if marker != version:
        fail("The commit subject says " + marker + " but " + SOURCE + " says " + version + ".")
    if not changelog_touched:
        fail("A commit that ships a version writes its entries into " + CHANGELOG + ".")

    entries = section_entries(changelog_text, version)
    if entries is None:
        fail(CHANGELOG + " has no section of its own for version " + version + ".")
    if not entries:
        fail("The " + version + " section of " + CHANGELOG + " has no entries.")
    if UNRELEASED_PATTERN.search(changelog_text) is not None:
        fail("A commit that ships a version leaves no Unreleased heading behind it.")

    notes = bullet_entries(body.splitlines())
    if not notes:
        fail("The commit body has to carry the release notes as bullet points.")
    if notes != entries:
        fail("The " + version + " changelog section and the commit body do not say the same thing.")

    tag = "v" + version
    if git("tag", "--list", tag).strip():
        fail("Version " + version + " has already been released as " + tag + ".")

    emit("release", "true")
    emit("version", version)
    emit("tag", tag)
    print("Publishing " + tag + ".")


main()
