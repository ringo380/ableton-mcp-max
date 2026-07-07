"""Mastering-selection intelligence: intent -> character bucket + target -> chain.

Pure module imported by server.py only. Parses a free-text intent into a
character bucket and optional platform, resolves the loudness target, and builds
the proposed Ozone chain via master_profiles. PROPOSE ONLY - never writes. The
catalog reuse-vs-create layer lives in server.py (it needs the catalog conn).
"""
import re

from ableton_mcp_max import master_profiles

REUSE_MIN_SCORE = 2
DEFAULT_TARGET = -14.0
DEFAULT_TRUE_PEAK = -1.0

# Character bucket -> keyword phrases (word-boundary matched).
BUCKET_VOCAB = {
    "loud_club":   ["loud", "club", "festival", "banging", "edm", "slammed"],
    "warm":        ["warm", "vintage", "analog", "analogue", "smooth", "vinyl"],
    "bright":      ["bright", "airy", "crisp", "presence", "sparkle", "sheen"],
    "punchy":      ["punchy", "punch", "transient", "snappy", "aggressive"],
    "transparent": ["transparent", "clean", "natural", "gentle", "subtle"],
}
DEFAULT_BUCKET = "transparent"

# Platform keyword -> integrated LUFS target.
PLATFORM_TARGETS = {
    "spotify": -14.0, "amazon": -14.0, "youtube": -14.0,
    "apple music": -16.0, "apple": -16.0,
    "club": -8.0, "dj": -8.0,
}


def _phrase_present(text, phrase):
    return re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text) is not None


def parse_intent(text):
    t = (text or "").lower()
    # Bucket: highest keyword count wins; ties -> BUCKET_VOCAB insertion order.
    keywords = []
    best_bucket, best_n = DEFAULT_BUCKET, 0
    for bucket, phrases in BUCKET_VOCAB.items():
        hits = [ph for ph in phrases if _phrase_present(t, ph)]
        keywords.extend(hits)
        if len(hits) > best_n:
            best_bucket, best_n = bucket, len(hits)
    # Platform: first match ("apple music" before "apple").
    platform = None
    for name in sorted(PLATFORM_TARGETS, key=len, reverse=True):
        if _phrase_present(t, name):
            platform = name
            break
    return {"bucket": best_bucket, "platform": platform, "keywords": keywords}


def resolve_target(parsed, target_arg):
    if target_arg is not None:
        return float(target_arg), "explicit"
    if parsed.get("platform"):
        return PLATFORM_TARGETS[parsed["platform"]], "platform:%s" % parsed["platform"]
    return DEFAULT_TARGET, "default"


def recommend(intent, target=None, true_peak=DEFAULT_TRUE_PEAK):
    parsed = parse_intent(intent)
    lufs, src = resolve_target(parsed, target)
    tp = DEFAULT_TRUE_PEAK if true_peak is None else float(true_peak)
    chain = master_profiles.build_chain(parsed["bucket"], lufs, tp)
    reason = "%s bucket, target %.1f LUFS (%s), ceiling %.1f dBTP." % (
        parsed["bucket"], lufs, src, tp)
    return {"intent": intent, "parsed": parsed, "target": lufs,
            "true_peak": tp, "chain": chain, "decision": "create",
            "reason": reason}
