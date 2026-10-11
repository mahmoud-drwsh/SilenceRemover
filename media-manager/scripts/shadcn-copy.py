"""Copy shadcn/ui components from saved registry JSON files into components/ui/.

Usage (from media-manager/):
  curl -sf -o <dir>/button.json https://ui.shadcn.com/r/styles/new-york-v4/button.json
  python3 -I scripts/shadcn-copy.py <dir>/button.json [...]

The script does the same import changes as the shadcn CLI, but for the
packages that this app uses (see the UI section in the foundation notes):
  - "cn" (the registry helper package) -> "@/lib/utils" (clsx + tailwind-merge).
  - "radix-ui" (the package that holds all primitives) -> the one
    "@radix-ui/react-<name>" package for each primitive.
  - "@/registry/new-york-v4/ui/<name>" (a registry dependency) ->
    "@/components/ui/<name>".
The script prints the npm dependencies of each item. Do the supply-chain
check for each new package before you install it, and read each copied file
before you commit it. The script does not change the component code.
"""

import json
import pathlib
import re
import sys

OUT = pathlib.Path(__file__).resolve().parent.parent / "components" / "ui"


def kebab(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()


def rewrite(source: str) -> str:
    source = source.replace('from "cn"', 'from "@/lib/utils"')
    source = source.replace('from "@/registry/new-york-v4/ui/', 'from "@/components/ui/')

    def radix(match: re.Match) -> str:
        lines = []
        for part in match.group(1).split(","):
            part = part.strip()
            if not part:
                continue
            name, _, alias = part.partition(" as ")
            name = name.strip()
            alias = (alias or name).strip()
            lines.append(f'import * as {alias} from "@radix-ui/react-{kebab(name)}"')
        return "\n".join(lines)

    return re.sub(r'import \{([^}]*)\} from "radix-ui"', radix, source)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for arg in sys.argv[1:]:
        item = json.loads(pathlib.Path(arg).read_text())
        deps = [d for d in item.get("dependencies", []) if d != "cn"]
        print(f"{item['name']}: dependencies {deps}, registry dependencies {item.get('registryDependencies')}")
        for file in item["files"]:
            if file.get("type") not in (None, "registry:ui"):
                print(f"  skipped {file['path']} ({file.get('type')})")
                continue
            target = OUT / pathlib.Path(file["path"]).name
            target.write_text(rewrite(file["content"]))
            print(f"  wrote {target.relative_to(OUT.parent.parent)}")


if __name__ == "__main__":
    main()
