"""Compile the XRDP parser with libc and the project string-copy fallback.

The nonnull sanitizer checks the libc header contract. Display-format helpers
are supplied by the test fixture.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

PREFIX = '#define _DEFAULT_SOURCE\n\n#include <assert.h>\n#include <ctype.h>\n#include <stdio.h>\n#include <stdlib.h>\n#include <string.h>\n#define MAX_DISPLAY_NAME_SIZE 32\n#define LOG(...) ((void)0)\n#define g_strncmp strncmp\n#define g_atoi atoi\n#define g_snprintf snprintf\n#define XRDP_CHANSRV_STR "/run/test/%d/xrdp_chansrv_socket_%s"\nstatic int g_get_display_string_from_x11_display(int n, char *out, size_t size) {\n return snprintf(out,size,"%d",n) >= (int)size ? -1 : 0;\n}\n'
SUFFIX = '\nint main(void) {\n char out[128]; char small[4];\n assert(parse_chansrvport("/run/test.sock",NULL,0,-1)==0);\n assert(parse_chansrvport("/run/test.sock",out,sizeof(out),1000)==0);\n assert(strcmp(out,"/run/test.sock")==0);\n assert(parse_chansrvport("/run/test.sock",small,sizeof(small),1000)==0);\n assert(strcmp(small,"/ru")==0);\n assert(parse_chansrvport("DISPLAY(200)",NULL,0,-1)==0);\n assert(parse_chansrvport("DISPLAY(200)",out,sizeof(out),1000)==0);\n assert(strcmp(out,"/run/test/1000/xrdp_chansrv_socket_200")==0);\n assert(parse_chansrvport("DISPLAY(200,1001)",out,sizeof(out),1000)==0);\n assert(strcmp(out,"/run/test/1001/xrdp_chansrv_socket_200")==0);\n assert(parse_chansrvport(NULL,NULL,0,-1)==-1);\n assert(parse_chansrvport("DISPLAY()",NULL,0,-1)==-1);\n assert(parse_chansrvport("DISPLAY(200,)",NULL,0,-1)==-1);\n assert(parse_chansrvport("DISPLAY(200",NULL,0,-1)==-1);\n puts("10 parser cases passed");\n return 0;\n}\n'


def probe(source: Path) -> dict[str, object]:
    raw = source.read_text()
    start = raw.index("static int\nparse_chansrvport(")
    end = raw.index(
        "\n/*****************************************************************************/",
        start,
    )
    parser = raw[start:end]
    string_source = source.parents[1] / "common/string_calls.c"
    strings = string_source.read_text()
    start = strings.index("size_t strlcpy(char *dst, const char *src, size_t dsize)")
    end = strings.index("\n#endif", start)
    fallback = strings[start:end].replace("strlcpy(", "xrdp_fallback_strlcpy(", 1)
    results = []
    with tempfile.TemporaryDirectory(prefix="xrdp-real-parser-") as directory:
        root = Path(directory)
        for binding in (
            "libc-plain",
            "libc-nonnull-sanitizer-trap",
            "actual-xrdp-fallback",
        ):
            code = PREFIX
            if binding == "actual-xrdp-fallback":
                code += fallback + "\n#define strlcpy xrdp_fallback_strlcpy\n"
            code += parser + SUFFIX
            test_source = root / "check.c"
            test_source.write_text(code)
            binary = root / "check"
            flags = (
                ["-fsanitize=nonnull-attribute", "-fsanitize-undefined-trap-on-error"]
                if binding == "libc-nonnull-sanitizer-trap"
                else []
            )
            build = subprocess.run(
                [
                    "cc",
                    "-std=c11",
                    "-O0",
                    "-Werror=implicit-function-declaration",
                    *flags,
                    str(test_source),
                    "-o",
                    str(binary),
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            if build.returncode:
                results.append(
                    {
                        "binding": binding,
                        "available": False,
                        "compileExitCode": build.returncode,
                    }
                )
                continue
            result = subprocess.run(
                [str(binary)], text=True, capture_output=True, check=False, timeout=10
            )
            results.append(
                {
                    "binding": binding,
                    "available": True,
                    "exitCode": result.returncode,
                    "parserCasesCompleted": result.returncode == 0,
                }
            )
    complete = all(item.get("available") is True for item in results)
    passed = complete and all(item.get("exitCode") == 0 for item in results)
    return {
        "sourceSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "stringSourceSha256": hashlib.sha256(string_source.read_bytes()).hexdigest(),
        "results": results,
        "allChecksAvailable": complete,
        "passed": passed,
        "scope": "Actual parser, actual libc/header and project fallback; display helpers substituted. Sanitizer trap is not an ordinary runtime or network crash.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Pinned checkout xrdp/xrdp_mm.c")
    args = parser.parse_args()
    result = probe(args.source)
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
