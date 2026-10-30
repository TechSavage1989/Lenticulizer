# Continuous integration

Alpha 32 private source contains a prepared Windows validation workflow. It is intentionally not published or active in this documentation-only repository because application-source publication has not been authorized.

The prepared workflow validates source/root checks, JavaScript and Python contracts, explicit NuGet restores, .NET build/parity tests, self-contained publish, embedded-core/runtime verification, and source-archive construction.

It does not publish a GitHub release, push tags, upload release binaries, change repository visibility, or require secrets.

Interactive Windows/WebView2 update install/relaunch/rollback and live Blender behavior remain separate release gates and are not treated as proven by hosted CI.
