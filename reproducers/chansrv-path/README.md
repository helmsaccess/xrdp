# Validation-only chansrv path regression

Requirements: Python 3, GCC with `-fsanitize=nonnull-attribute`, patch, and glibc headers declaring the strlcpy destination nonnull. Recorded versions: GCC 16.2.1, glibc 2.43 on Fedora Linux 44. From this directory:

```sh
python3 reproduce-xrdp.py ../.. fix.patch > result.json
```

The runner checks the source and patch hashes, compiles the actual path parser with libc and the actual XRDP string-copy fallback, and tests temporary copies. Display-format helpers are supplied by the test fixture.

Expected results:

- The original validation-only call traps with the nonnull sanitizer (recorded subprocess exit -4, SIGILL).
- With the fix, the instrumented build passes all ten cases.
- Normal libc and XRDP fallback builds each pass all ten cases both before and after the fix.

The compiler uses `-fsanitize-undefined-trap-on-error`; no sanitizer runtime library is required. The runner checks all expected outcomes and removes temporary files.
