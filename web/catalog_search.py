"""Shared, stable pagination for the posts and profiles catalogues."""

CATALOG_PAGE_SIZE = 20
CATALOG_SORT = [('created_at', -1), ('_id', -1)]


def parse_catalog_offset(value):
    """Treat missing, malformed and negative offsets as the first page."""
    try:
        return min(2**63 - 1, max(0, int(value)))
    except (TypeError, ValueError, OverflowError):
        return 0


async def catalog_page(collection, query, offset=0):
    """Read a page plus a lookahead; tie-break timestamps consistently by ID."""
    offset = parse_catalog_offset(offset)
    docs = await (collection.find(query).sort(CATALOG_SORT).skip(offset)
                  .limit(CATALOG_PAGE_SIZE + 1).to_list(length=CATALOG_PAGE_SIZE + 1))
    return docs[:CATALOG_PAGE_SIZE], len(docs) > CATALOG_PAGE_SIZE
