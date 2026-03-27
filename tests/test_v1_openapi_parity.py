import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server.py"
OPENAPI_V16 = ROOT / "config" / "contracts" / "v5" / "openapi_full_v1.6.yaml"


def _extract_spec_methods_from_yaml_text(text: str) -> dict[str, set[str]]:
    paths: dict[str, set[str]] = {}
    current_path: str | None = None
    for line in text.splitlines():
        path_match = re.match(r"^  (/v1/[^:\n]+):\s*$", line)
        if path_match:
            current_path = path_match.group(1)
            paths[current_path] = set()
            continue
        method_match = re.match(r"^    (get|post|put|delete):\s*$", line)
        if method_match and current_path:
            paths[current_path].add(method_match.group(1).upper())
    return paths


def _extract_server_methods(text: str) -> dict[str, set[str]]:
    get_block = text.split("def do_GET", 1)[1].split("def do_POST", 1)[0]
    post_block = text.split("def do_POST", 1)[1].split("def do_PUT", 1)[0]
    put_block = text.split("def do_PUT", 1)[1].split("def do_DELETE", 1)[0]
    delete_block = text.split("def do_DELETE", 1)[1]

    out: dict[str, set[str]] = {}

    for p in re.findall(r'if path == "(/v1/[^"]+)"', get_block):
        out.setdefault(p, set()).add("GET")
    for p in re.findall(r'if path.startswith\("(/v1/[^"]+)"\)', get_block):
        out.setdefault(p, set()).add("GET_DYNAMIC")

    for p in re.findall(r'if parsed\.path == "(/v1/[^"]+)"', post_block):
        out.setdefault(p, set()).add("POST")
    for p in re.findall(r'if parsed\.path == "(/v1/[^"]+)"', put_block):
        out.setdefault(p, set()).add("PUT")
    for p in re.findall(r'if parsed\.path == "(/v1/[^"]+)"', delete_block):
        out.setdefault(p, set()).add("DELETE")

    return out


def _path_has_method(server_methods: dict[str, set[str]], spec_path: str, method: str) -> bool:
    if method in server_methods.get(spec_path, set()):
        return True
    if "{" in spec_path and "}" in spec_path and method == "GET":
        # /v1/variants/{variant_id} -> /v1/variants/
        prefix = spec_path.split("{", 1)[0]
        if "GET_DYNAMIC" in server_methods.get(prefix, set()):
            return True
    return False


class TestV1OpenApiParity(unittest.TestCase):
    def test_v16_spec_file_exists(self) -> None:
        self.assertTrue(OPENAPI_V16.exists(), f"OpenAPI v1.6 file is missing: {OPENAPI_V16}")

    def test_required_v1_paths_and_methods_present_in_server(self) -> None:
        spec_text = OPENAPI_V16.read_text(encoding="utf-8")
        server_text = SERVER.read_text(encoding="utf-8")

        spec_methods = _extract_spec_methods_from_yaml_text(spec_text)
        server_methods = _extract_server_methods(server_text)

        self.assertTrue(spec_methods, "No /v1 paths extracted from OpenAPI v1.6")
        self.assertTrue(server_methods, "No /v1 methods extracted from server.py")

        missing: list[str] = []
        for path, methods in sorted(spec_methods.items()):
            for method in sorted(methods):
                if not _path_has_method(server_methods, path, method):
                    missing.append(f"{method} {path}")

        self.assertEqual(
            missing,
            [],
            "Missing OpenAPI v1.6 contract methods in server:\n" + "\n".join(missing),
        )


if __name__ == "__main__":
    unittest.main()
