---
layout: default
title: Catalog
parent: Tools
nav_order: 22
---

# Catalog
{: .no_toc }

Persistent local index of Serum presets, samples, grooves, and device presets, with similarity search and reuse-vs-create recommendation that can orchestrate the existing create tools.

<details open markdown="block">
  <summary>Tools on this page</summary>
  {: .text-delta }
1. TOC
{:toc}
</details>

---

## search_catalog

```python
search_catalog(
    query: str,
    domains: list = None,
    kinds: list = None,
    sources: list = None,
    limit: int = 50,
)
```

Search the local content catalog (Serum presets, samples, grooves, device
presets) by name/folder/tags. Fast persistent index; auto-refreshes changed
filesystem roots. Returns {ok, data:{count, returned, truncated, items}}.

## find_similar

```python
find_similar(intent: str, domain: str, limit: int = 10)
```

Rank catalog assets in one domain by lexical similarity to an intent
string, with scores. domain in serum|sample|groove|device_preset. Returns
{ok, data:{items:[{name, path, uri, source, folder, kind, score}]}}.

## catalog_stats

```python
catalog_stats()
```

Counts and freshness for the local catalog by domain/source/kind, plus
per-root last-indexed times. Returns {ok, data:{total, by_domain, by_source,
by_kind, roots, device_presets_last_indexed}}.

## reindex_catalog

```python
reindex_catalog(domains: list = None, full: bool = False)
```

Rebuild the catalog. domains defaults to all. full=True drops and rebuilds
from scratch. Device presets reindex only when Live is connected. Returns
{ok, data:{indexed:{domain:count}, errors:[...]}}.

## recommend_asset

```python
recommend_asset(intent: str, domain: str)
```

Propose reuse-vs-create for a described asset. domain in
serum|sample|groove|device_preset|wavetable|simpler. Returns {ok, data:
{decision, top_matches, create_plan, reason}}. PROPOSE ONLY - never writes;
pass create_plan to create_from_plan(confirm=True) to act on a 'create'.

## recommend_instrument

```python
recommend_instrument(intent: str, prefer_native: bool = None)
```

Choose which instrument engine to reach for from a free-text intent
(e.g. 'gritty evolving reese bass for dnb'). Ranks Serum vs native Wavetable,
Operator, Analog, Simpler/Sampler, and Drum Rack against a capability matrix,
biased toward native engines so Serum is used only when it earns it. Applies
live signals when connected: Serum-installed (drops Serum if absent), Serum
instance count (busy penalty), and portability (prefer_native). Set
prefer_native=True to force native-only weighting; leave None to auto-detect
(native-preferred only when the set has no 3rd-party plugin). PROPOSE ONLY -
pass the returned top.domain to recommend_asset to pick reuse-vs-create.
Returns {ok, data:{intent, parsed, ranked, top, reason, environment, next}}.

## create_from_plan

```python
create_from_plan(plan: dict, confirm: bool = False)
```

Execute a create_plan from recommend_asset. confirm=False (default)
returns a dry-run describing what would be created and writes nothing.
confirm=True invokes the matching creator (Wavetable, Simpler, or a Serum
base-preset clone). Returns {ok, data:{...}}.

