---
layout: default
title: Host Lifecycle
parent: Tools
nav_order: 17
---

# Host Lifecycle
{: .no_toc }

Save the set and gracefully quit/relaunch Ableton Live (no crash-recovery prompt) for an automated bounce after a Remote Script change.

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
  for a set that already has a file — an Untitled set has no name and the
  quit is reported as failed, so save it first via save_set_as).
relaunch: reopen Live after it quits (default True), then wait up to
  wait_timeout seconds for the control surface to rebind port 9877.

Returns JSON {ok, data:{app, was_dirty, quit, relaunched, surface_up, ...}}.
NOTE: this only restarts ABLETON. A server.py change still needs a Claude
Code restart (the MCP server can't restart its own process); a Remote-Script
change is fully covered by reinstalling the script + this bounce. Discarding
unsaved work is irreversible — prefer the /ableton:restart command, which
asks before discarding.

## save_set

```python
save_set(name: str = '')
```

Save the current Live set to disk (there is no LOM save API — this drives
Live's save UI: via System Events on macOS, so Live must have Accessibility
permission; via Live's menu and the Windows Save dialog on Windows. A
Save-As briefly brings Live to the front).

name: leave empty to save a TITLED set in place (File > Save Live Set; a
  no-op if clean). For an UNTITLED set you MUST pass a name (an empty call
  returns an error). A non-empty name always Saves-As under that name.
The set is saved to Live's last-used save location (Ableton wraps it in a
'<name> Project' folder unless that location is already inside a project);
the tool controls the NAME, not the directory. A name may not contain '/'
or ':' (on Windows, none of \ / : * ? " < > | either).

Returns JSON {ok, data:{saved, title|name, path?, untitled?, error?}}.
'path' is the saved file: exact on Windows (read off the Save dialog),
best-effort on macOS (it searches common save folders). Confirmation is by
the window title; verify on disk if it matters.

## save_set_as

```python
save_set_as(name: str)
```

Save the current Live set under a new NAME (File > Save Live Set As). Use
for an Untitled set, or to save a copy under a new name. Drives Live's save
UI (System Events on macOS - needs Accessibility permission; the Windows
Save dialog on Windows) and briefly focuses Live. An existing file of the
same name is replaced.

name: the set name (not a path). Saved to Live's last-used save location,
  wrapped in a '<name> Project' folder unless that location is already
  inside a project - the tool controls the name, not the directory. A name
  may not contain '/' or ':' (on Windows, none of \ / : * ? " < > |).

Returns JSON {ok, data:{saved, name, path?, error?}}. 'path' is exact on
Windows, best-effort on macOS; confirmation is by the window title.

