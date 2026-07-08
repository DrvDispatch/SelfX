"""hash-checksum: compute MD5/SHA/BLAKE2/SHA-3/CRC32 checksums of a file."""

import hashlib
import zlib

from .base import Tool, ToolContext, ToolError
from .registry import register

# 'all' expands to exactly the four classic digests (unchanged default output).
_ALGOS = ["md5", "sha1", "sha256", "sha512"]
# Every selectable algorithm. BLAKE2 and SHA-3 come from hashlib (no new deps);
# crc32 is handled specially via zlib.
_ALL_ALGOS = _ALGOS + ["blake2b", "blake2s", "sha3_256", "sha3_512", "crc32"]


class _Crc32:
    """hashlib-like adapter over zlib.crc32 so it fits the same update/hexdigest loop."""

    def __init__(self) -> None:
        self._value = 0

    def update(self, data: bytes) -> None:
        self._value = zlib.crc32(data, self._value)

    def hexdigest(self) -> str:
        return format(self._value & 0xFFFFFFFF, "08x")


def _new_hasher(algo: str):
    if algo == "crc32":
        return _Crc32()
    return hashlib.new(algo)


@register
class HashChecksum(Tool):
    slug = "hash-checksum"
    name = "File checksum"
    category = "utilities"
    description = "Compute MD5, SHA, BLAKE2, SHA-3 or CRC32 hashes of a file to verify integrity."
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
                "enum": ["all", *_ALL_ALGOS],
                "default": "all",
            },
            "expected": {
                "type": "string",
                "title": "Expected hash (verify)",
                "description": (
                    "Optional: paste a known hex digest to verify the file against. "
                    "The result reports MATCH or MISMATCH."
                ),
                "maxLength": 256,
            },
        },
    }

    def run(self, ctx: ToolContext) -> None:
        choice = str(ctx.params.get("algorithm", "all"))
        algos = _ALGOS if choice == "all" else [choice]
        # hashlib.new() raises ValueError when an algorithm is disabled (e.g. md5
        # under an OpenSSL FIPS build). Skip unavailable algorithms in 'all' mode;
        # for a specific request, report it clearly instead of crashing the job.
        hashers = {}
        for a in algos:
            try:
                hashers[a] = _new_hasher(a)
            except ValueError:
                if choice != "all":
                    raise ToolError(
                        f"the {a} algorithm is not available on this server"
                    ) from None
        if not hashers:
            raise ToolError("no supported hash algorithm is available on this server")
        src = ctx.input_paths[0]
        ctx.progress(0.3, "hashing")
        with src.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 22), b""):
                for h in hashers.values():
                    h.update(chunk)
        digests = {name: h.hexdigest() for name, h in hashers.items()}
        lines = [f"{name}: {hexd}" for name, hexd in digests.items()]

        # Optional verify: compare the expected hex against every computed digest
        # (case-insensitively) so it works regardless of which algorithm produced it.
        expected = str(ctx.params.get("expected", "") or "").strip().lower()
        if expected:
            matched = [name for name, hexd in digests.items() if hexd.lower() == expected]
            if matched:
                lines.append(f"verify: MATCH ({', '.join(matched)})")
            else:
                lines.append("verify: MISMATCH")
        (ctx.output_dir / "checksums.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        ctx.progress(1.0, "done")
