import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "iftar_sayaci.py")
VERSION_PATTERN = re.compile(r"^APP_VERSION\s*=\s*[\"']([^\"']+)[\"']", re.MULTILINE)
PRODUCT_NAME = "İftar Sayacı"
INTERNAL_NAME = "IftarSayaci"
EXECUTABLE_NAME = "IftarSayaci.exe"

TEMPLATE = """VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={numbers},
    prodvers={numbers},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('FileDescription', '{product}'),
        StringStruct('FileVersion', '{version}'),
        StringStruct('InternalName', '{internal}'),
        StringStruct('OriginalFilename', '{executable}'),
        StringStruct('ProductName', '{product}'),
        StringStruct('ProductVersion', '{version}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def fail(message):
    print("::error::" + message)
    sys.exit(1)


def read_text(path):
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read().replace("\r\n", "\n").replace("\r", "\n")


def source_version():
    match = VERSION_PATTERN.search(read_text(SOURCE))
    if match is None:
        fail("APP_VERSION was not found in " + SOURCE + ".")
    return match.group(1).strip()


def version_numbers(version):
    parts = []
    for part in version.split("."):
        if not part.isdigit():
            fail("APP_VERSION has to be numbers separated by dots: " + version)
        parts.append(int(part))
    if len(parts) > 4:
        fail("APP_VERSION has more than four parts: " + version)
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts)


def render(version):
    return TEMPLATE.format(
        numbers=version_numbers(version),
        version=version,
        product=PRODUCT_NAME,
        internal=INTERNAL_NAME,
        executable=EXECUTABLE_NAME,
    )


def write(destination):
    version = source_version()
    with open(destination, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(render(version))
    print("Wrote " + destination + " for version " + version + ".")


def main():
    arguments = sys.argv[1:]
    if arguments and arguments[0] == "show":
        print(source_version())
        return
    if len(arguments) != 1:
        fail("Usage: version_info.py show | version_info.py DESTINATION")
    write(arguments[0])


main()
