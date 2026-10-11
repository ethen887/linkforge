"""Build a reopenable course URL from a verified Chaoxing card snapshot."""

from urllib.parse import parse_qs, quote, unquote_plus, urlsplit, urlunsplit

from linkforge.platforms.chaoxing.models import ChaoxingPageState


def course_resume_url(page_url: str, state: ChaoxingPageState) -> str | None:
    """Preserve course routing parameters, replacing the chapter and card only.

    Card navigation can replace an iframe without updating the address bar.
    Save the outer studentstudy route, never a bare cards/video iframe URL.
    Keep unrelated query components verbatim, including encoded auth values.
    """
    page = urlsplit(page_url)
    if (
        page.scheme not in {"http", "https"}
        or not page.hostname
        or page.path.rstrip("/") not in {"/mycourse/studentstudy", "/mooc-ans/mycourse/studentstudy"}
        or not state.knowledge_id
    ):
        return None
    card_query = parse_qs(urlsplit(state.content_frame_url).query)
    card_numbers = card_query.get("num", [])
    if len(card_numbers) != 1 or not card_numbers[0].isascii() or not card_numbers[0].isdigit():
        return None

    chapter_keys = {"chapterid", "knowledgeid"}
    parts: list[str] = []
    has_chapter = False
    has_card = False
    for component in page.query.split("&") if page.query else []:
        raw_key = component.partition("=")[0]
        key = unquote_plus(raw_key).lower()
        if key in chapter_keys:
            parts.append(f"{raw_key}={quote(state.knowledge_id, safe='')}")
            has_chapter = True
        elif key == "num":
            parts.append(f"{raw_key}={card_numbers[0]}")
            has_card = True
        else:
            parts.append(component)
    if not has_chapter:
        parts.append(f"chapterId={quote(state.knowledge_id, safe='')}")
    if not has_card:
        parts.append(f"num={card_numbers[0]}")
    return urlunsplit(page._replace(query="&".join(parts)))
