# Internal candidate finding: native save ignores writer close failure

This is an AI-assisted internal fork note, **not an upstream submission**.
No issue, comment, or patch has been submitted.

## Policy and destination

The original project is [GNOME Dia](https://gitlab.gnome.org/GNOME/dia), as
identified by this checkout's `HACKING.md`. Its local `README.md`, section
“Use of Generative AI”, explicitly excludes AI-generated contributions including
issues, documentation, and code. `HACKING.md` points to that policy. Therefore
this note and patch must not be submitted upstream as generated contributions.
A human would need to investigate independently and comply with the applicable
policy; merely approving or rephrasing this note does not remove the restriction.

On 2026-09-19, attempts to fetch the upstream README and search GitLab issues for
`xmlSaveClose` were inaccessible through the browsing tool. Current remote policy,
duplicate issue status, and whether upstream already fixed this are unverified.

## Local evidence

In the checkout based on `7093ae39a`, `lib/dia-io.c:dia_io_save_document` sets
`result = TRUE` after `xmlSaveDoc` and `xmlSaveFlush`. Its cleanup invokes
`write_context_free`, which called `xmlSaveClose` without checking the result.
`write_context_close` returns `-1` when `g_output_stream_close` fails; that return
was therefore not reflected in the save result.

Closing may flush a compressor and commit GIO's atomic replacement stream.
A close-only write failure could therefore be reported as a successful save,
allowing the caller to clear the editor's dirty state. This is a code-path finding;
a fault-injected failure on an unmodified upstream revision has **not** been
reproduced, so upstream impact remains a candidate rather than a confirmed report.

## Fork change and validation limits

The fork explicitly calls `xmlSaveClose` before cleanup, records a negative result
as failure, and nulls the writer pointer to avoid double close. Existing earlier
failures remain failures. The live adapter independently stages output, rejects
empty files, and updates filename and undo saved state only after publication.

Portable adapter tests cover failed staging, overwrite refusal, publication races,
symlink rejection, and dirty-state preservation. Native round-trip coverage lives
in `mcp/tests/test_live_files_native.py`. Neither substitutes for a deterministic
injected stream-close failure; that specific regression remains to be exercised.
