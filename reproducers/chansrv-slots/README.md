# Dynamic-channel slot regression

For https://github.com/neutrinolabs/xrdp/pull/3888. The included patch is the existing PR author's fix.

Requirements: Python 3, Git, patch, and a C compiler. From this directory:

```sh
python3 reproduce.py ../.. reference.patch > result.json
```

The runner reads XRDP commit `62987220b8550d5fef750ba5678c5ea987d92902` from the checkout and compiles its allocator, disconnect block and reset function in temporary copies. Transport and supporting services are simulated. Dechunkers are small allocated test objects with a live-object counter.

Expected results:

- Original: the second allocation of cycle 128 fails, with 255 occupied slots.
- With the patch: 1,000 cycles complete, 2,000 dynamic clients close and all 2,000 dechunker test objects are freed. The static client remains connected.

The outer runner succeeds only when both observations match. It removes temporary files when finished.
