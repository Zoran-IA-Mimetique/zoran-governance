from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import re


_POS_HEADINGS: tuple[tuple[str, str], ...] = (
    ("forme de verbe", "VERB"),
    ("forme d'adjectif", "ADJECTIVE"),
    ("forme de nom", "NOUN"),
    ("nom propre", "PROPER_NOUN"),
    ("nom commun", "NOUN"),
    ("verbe", "VERB"),
    ("adjectif", "ADJECTIVE"),
    ("adverbe", "ADVERB"),
    ("pronom", "PRONOUN"),
    ("déterminant", "DETERMINER"),
    ("preposition", "PREPOSITION"),
    ("préposition", "PREPOSITION"),
    ("conjonction", "CONJUNCTION"),
    ("interjection", "INTERJECTION"),
    ("particule", "PARTICLE"),
)


@dataclass(frozen=True)
class WiktionarySense:
    pos: str
    heading: str
    definition: str


@dataclass(frozen=True)
class WiktionaryEntry:
    surface: str
    language: str
    revision_id: int | None
    senses: tuple[WiktionarySense, ...]
    source_uri: str


class _FrenchEntryHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_french = False
        self.current_pos: str | None = None
        self.current_heading = ""
        self._heading_tag: str | None = None
        self._heading_parts: list[str] = []
        self._ol_depth = 0
        self._li_capture = False
        self._li_parts: list[str] = []
        self._nested_list_depth = 0
        self._ignored_depth = 0
        self.senses: list[WiktionarySense] = []

    @staticmethod
    def _clean(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip(" \n\t;:")

    @staticmethod
    def _pos_for_heading(heading: str) -> str | None:
        normalized = heading.casefold().replace("’", "'")
        for marker, pos in _POS_HEADINGS:
            if marker in normalized:
                return pos
        return None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"h2", "h3", "h4", "h5"}:
            self._heading_tag = tag
            self._heading_parts = []
            return
        if not self.in_french:
            return
        if tag == "ol":
            self._ol_depth += 1
            if self._li_capture:
                self._nested_list_depth += 1
        elif tag == "ul" and self._li_capture:
            self._nested_list_depth += 1
        elif tag == "li" and self.current_pos and self._ol_depth == 1 and not self._li_capture:
            self._li_capture = True
            self._li_parts = []
            self._nested_list_depth = 0
        elif tag in {"sup", "style", "script"} and self._li_capture:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._heading_tag == tag:
            heading = self._clean("".join(self._heading_parts))
            if tag == "h2":
                self.in_french = heading.casefold().startswith("français")
                self.current_pos = None
                self.current_heading = ""
            elif self.in_french:
                self.current_heading = heading
                self.current_pos = self._pos_for_heading(heading)
            self._heading_tag = None
            self._heading_parts = []
            return
        if not self.in_french:
            return
        if tag in {"sup", "style", "script"} and self._li_capture and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if tag == "ul" and self._li_capture and self._nested_list_depth:
            self._nested_list_depth -= 1
            return
        if tag == "ol" and self._li_capture and self._nested_list_depth:
            # A nested ordered list changes both counters. Restore both on close.
            self._nested_list_depth -= 1
            if self._ol_depth:
                self._ol_depth -= 1
            return
        if tag == "li" and self._li_capture:
            definition = self._clean("".join(self._li_parts))
            if definition and self.current_pos:
                self.senses.append(WiktionarySense(self.current_pos, self.current_heading, definition))
            self._li_capture = False
            self._li_parts = []
            self._nested_list_depth = 0
            self._ignored_depth = 0
            return
        if tag == "ol" and self._ol_depth:
            self._ol_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._heading_tag is not None:
            self._heading_parts.append(data)
        elif self._li_capture and self._nested_list_depth == 0 and self._ignored_depth == 0:
            self._li_parts.append(data)


def parse_french_wiktionary_html(
    surface: str,
    html: str,
    *,
    revision_id: int | None = None,
    source_uri: str = "https://fr.wiktionary.org/",
) -> WiktionaryEntry:
    if not surface.strip() or len(surface) > 200:
        raise ValueError("invalid surface")
    if not isinstance(html, str) or not html.strip() or len(html) > 5_000_000:
        raise ValueError("invalid Wiktionary HTML")
    parser = _FrenchEntryHTMLParser()
    parser.feed(html)
    parser.close()
    return WiktionaryEntry(
        surface=surface.strip(),
        language="fr",
        revision_id=revision_id,
        senses=tuple(parser.senses),
        source_uri=source_uri,
    )
