"""hash-checksum: compute MD5/SHA checksums of a file."""

import hashlib

from .base import Tool, ToolContext
from .registry import register

_ALGOS = ["md5", "sha1", "sha256", "sha512"]


@register
class HashChecksum(Tool):
    slug = "hash-checksum"
    name = "File checksum"
    category = "utilities"
    description = "Compute MD5 and SHA hashes of a file to verify its integrity."
    accepts = []  # any file type
    multi_file = False
    min_files = 1
    queue = "default"
    params_schema = {
        "type": "object",
        "properties": {
            "algorithm": {
                "type": "string",
                "title": "Algorithm",
                "enum": ["all", "md5", "sha1", "sha256", "sha512"],
                "default": "all",
            }
        },
    }

    def run(self, ctx: ToolContext) -> None:
        choice = str(ctx.params.get("algorithm", "all"))
        algos = _ALGOS if choice == "all" else [choice]
        hashers = {a: hashlib.new(a) for a in algos}
        src = ctx.input_paths[0]
        ctx.progress(0.3, "hashing")
        with src.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                for h in hashers.values():
                    h.update(chunk)
        lines = [f"{name}: {h.hexdigest()}" for name, h in hashers.items()]
        (ctx.output_dir / "checksums.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        ctx.progress(1.0, "done")
