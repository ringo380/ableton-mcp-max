---
layout: default
title: Host Lifecycle
parent: Tools
nav_order: 14
---

# Host Lifecycle
{: .no_toc }

Gracefully quit and relaunch Ableton Live (no crash-recovery prompt) for an automated bounce after a Remote Script change.

<details open markdown="block">
  <summary>Tools on this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

---

## restart_live

```python
restart_live(save: str = 'discard', relaunch: bool = True, wait_timeout: float = 90.0)
```

Gracefully quit and relaunch the running Ableton Live (no crash-recovery
prompt). Use this for an automated Live bounce after a Remote Script change.

save: how to handle UNSAVED changes if Live prompts on quit —
  'discard' (default; lose unsaved edits) or 'save' (overwrite; only works
  for a set that already has a file — an Untitled set has no path and the
  quit is reported as failed so you can save it by hand first).
relaunch: reopen Live after it quits (default True), then wait up to
  wait_timeout seconds for the control surface to rebind port 9877.

Returns JSON {ok, data:{app, was_dirty, quit, relaunched, surface_up, ...}}.
NOTE: this only restarts ABLETON. A server.py change still needs a Claude
Code restart (the MCP server can't restart its own process); a Remote-Script
change is fully covered by reinstalling the script + this bounce. Discarding
unsaved work is irreversible — prefer the /ableton:restart command, which
asks before discarding.

