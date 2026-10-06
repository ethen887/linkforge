"""Completion evidence for an entire Chaoxing knowledge node."""

from urllib.parse import parse_qs, urlsplit

CATALOG_STATE_SCRIPT = """
    const catalogNodes = Array.from(document.querySelectorAll('.posCatalog_select[id^="cur"]'));
    const catalog = catalogNodes.map(node => ({
        node_id: node.id,
        active: node.classList.contains("posCatalog_active"),
        completed_count: Array.from(node.querySelectorAll(":scope > .icon_Completed"))
            .filter(marker => marker.getClientRects().length > 0
                && getComputedStyle(marker).visibility !== "hidden").length,
        pending_count: node.querySelectorAll(":scope > .catalog_points_yi").length,
    }));
"""


def knowledge_is_completed(results: tuple[object, ...], card_url: str) -> bool:
    """Require a unique active node matching the loaded card and an explicit check.

    Missing catalogs provide no completion evidence. A present but inconsistent
    catalog fails closed, including during navigation between knowledge nodes.
    """
    catalogs: list[list[object]] = []
    for result in results:
        if not isinstance(result, dict):
            raise ValueError("Malformed catalog frame")
        catalog = result.get("catalog", [])
        if not isinstance(catalog, list):
            raise ValueError("Malformed catalog state")
        if catalog:
            catalogs.append(catalog)
    if not catalogs:
        return False
    if len(catalogs) != 1:
        raise ValueError("Ambiguous catalog frames")
    seen: set[str] = set()
    active: list[dict[str, object]] = []
    for node in catalogs[0]:
        if not isinstance(node, dict):
            raise ValueError("Malformed catalog node")
        node_id = node.get("node_id")
        if not isinstance(node_id, str) or not node_id.startswith("cur") or not node_id[3:].isdigit():
            raise ValueError("Malformed catalog identity")
        if node_id in seen:
            raise ValueError("Duplicate catalog identity")
        seen.add(node_id)
        if not isinstance(node.get("active"), bool):
            raise ValueError("Malformed catalog active state")
        counts = (node.get("completed_count"), node.get("pending_count"))
        if any(type(count) is not int or count not in (0, 1) for count in counts):
            raise ValueError("Malformed catalog completion markers")
        if counts == (1, 1):
            raise ValueError("Conflicting catalog completion markers")
        if node["active"]:
            active.append(node)
    parsed = urlsplit(card_url)
    query = parsed.query
    if not query and parsed.scheme == "data":
        query = parsed.fragment.partition("?")[2]
    knowledge_ids = parse_qs(query).get("knowledgeid", [])
    if len(active) != 1 or len(knowledge_ids) != 1 or active[0]["node_id"] != f"cur{knowledge_ids[0]}":
        raise ValueError("Catalog and card identity disagree")
    return active[0]["completed_count"] == 1
