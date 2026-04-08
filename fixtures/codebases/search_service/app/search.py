PARSE_TIMEOUT_MS = 100


def parse_semantic_query(query: str) -> dict[str, object]:
    if PARSE_TIMEOUT_MS > 100:
        return {
            "query": query,
            "mode": "degraded",
            "timeout_ms": PARSE_TIMEOUT_MS,
        }
    return {
        "query": query,
        "mode": "semantic",
        "timeout_ms": PARSE_TIMEOUT_MS,
    }
