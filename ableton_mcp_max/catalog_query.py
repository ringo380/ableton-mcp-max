"""Read side of the catalog: FTS narrowing + token scoring, similarity, stats."""
import re

_ITEM_COLS = ("name", "path", "uri", "source", "folder", "kind", "loadable",
              "domain")


def _terms(text):
    return [t for t in re.split(r"[\W_]+", (text or "").lower()) if t]


def score_tokens(intent, name, folder, tags):
    terms = _terms(intent)
    if not terms:
        return 0
    hay = " ".join([name or "", folder or "", tags or ""]).lower()
    name_words = set(_terms(name))
    score = 0
    for t in terms:
        if t in hay:
            score += 1
        if t in name_words:
            score += 1
    return score


def _fts_query(text):
    terms = _terms(text)
    if not terms:
        return None
    return " OR ".join('"%s"' % t for t in terms)


def _candidate_rows(conn, query, domains, kinds, sources):
    where, args = [], []
    if domains:
        where.append("domain IN (%s)" % ",".join("?" * len(domains)))
        args += list(domains)
    if kinds:
        where.append("kind IN (%s)" % ",".join("?" * len(kinds)))
        args += list(kinds)
    if sources:
        where.append("source IN (%s)" % ",".join("?" * len(sources)))
        args += list(sources)
    fts = _fts_query(query)
    if fts:
        sql = ("SELECT items.*, items.tags AS _tags FROM items_fts"
               " JOIN items ON items.id=items_fts.rowid"
               " WHERE items_fts MATCH ?")
        a = [fts]
        if where:
            sql += " AND " + " AND ".join(where)
            a += args
    else:
        sql = "SELECT items.*, items.tags AS _tags FROM items"
        if where:
            sql += " WHERE " + " AND ".join(where)
        a = args
    return conn.execute(sql, a).fetchall()


def _row_dict(r, score=None):
    d = {c: r[c] for c in _ITEM_COLS}
    if score is not None:
        d["score"] = score
    return d


def search_catalog(conn, query, domains=None, kinds=None, sources=None,
                   limit=50):
    rows = _candidate_rows(conn, query, domains, kinds, sources)
    scored = [(score_tokens(query, r["name"], r["folder"], r["tags"]), r)
              for r in rows]
    if _terms(query):
        scored.sort(key=lambda x: (-x[0], x[1]["name"] or ""))
    else:
        scored.sort(key=lambda x: (x[1]["name"] or ""))
    total = len(scored)
    shown = scored[:limit] if limit and limit > 0 else scored
    return {
        "count": total,
        "returned": len(shown),
        "truncated": len(shown) < total,
        "items": [_row_dict(r) for _s, r in shown],
    }


def find_similar(conn, intent, domain, limit=10):
    rows = _candidate_rows(conn, intent, [domain], None, None)
    scored = [(score_tokens(intent, r["name"], r["folder"], r["tags"]), r)
              for r in rows]
    scored.sort(key=lambda x: (-x[0], x[1]["name"] or ""))
    out = []
    for s, r in scored[:limit] if limit and limit > 0 else scored:
        out.append(_row_dict(r, score=s))
    return out


def catalog_stats(conn):
    def counts(col):
        return {row[0]: row[1] for row in conn.execute(
            "SELECT %s, count(*) FROM items GROUP BY %s" % (col, col))
            if row[0] is not None}
    total = conn.execute("SELECT count(*) FROM items").fetchone()[0]
    roots = [{"root_path": r["root_path"], "domain": r["domain"],
              "source": r["source"], "last_indexed": r["last_indexed"]}
             for r in conn.execute("SELECT * FROM roots")]
    dp = conn.execute(
        "SELECT last_indexed FROM roots WHERE domain='device_preset'").fetchone()
    return {
        "total": total,
        "by_domain": counts("domain"),
        "by_source": counts("source"),
        "by_kind": counts("kind"),
        "roots": roots,
        "device_presets_last_indexed": dp["last_indexed"] if dp else None,
    }
