"""Tina Phase 4: human-confirmed tag-tree building (the PRD's Class-3 repair).

This is the highest-risk structural repair in the product: it writes a
marked-content tag tree into a copy of an untagged PDF. Every semantic role it
applies (h1/h2/h3/p/li) was confirmed by a human; the model never decides
structure, and blocks left undecided default to plain paragraphs rather than
to a guess. Reading order, when supplied, reorders only the logical structure
elements — the visual content streams are never reordered.

Anti-vandal contract (asserted, never trusted): after building the tag tree,
the output is re-opened with a fresh parser and must show the identical page
count and byte-identical per-page extracted text as the source. Any deviation
raises RemediationError and produces no output bytes. When block roles cannot
be confidently mapped onto the document's content streams — merged runs,
glyph-ID subset fonts, existing marked content — the tool declines honestly
and routes the user to the accessible HTML working-copy rebuild instead of
guessing. No output of this module is a conformance claim.
"""
from __future__ import annotations

import io
import re
from hashlib import sha256
from typing import Any

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    BooleanObject,
    ContentStream,
    DictionaryObject,
    NameObject,
    NumberObject,
)

from tina.derive import DerivationError, extract_blocks
from tina.kernel import ToolGateway, ToolManifest
from tina.remedy import RemediationError

REMEDIATE_STRUCTURE_PERMISSION = "document.remediate.structure"

ALLOWED_ROLES = {"h1", "h2", "h3", "p", "li"}
_ROLE_TO_TAG = {"h1": "H1", "h2": "H2", "h3": "H3", "p": "P"}

_TEXT_SHOW_OPS = {b"Tj", b"TJ", b"'", b'"'}
_RUN_START_OPS = {b"Td", b"TD", b"Tm", b"T*"}
# The full marked-content operator family (PDF 32000-1 §14.6): sequences
# (BDC/BMC/EMC) and points (MP/DP). Any of them means someone already
# authored marked content here, so rebuilding would be vandalism.
_MARKED_CONTENT_OPS = {b"BDC", b"BMC", b"EMC", b"MP", b"DP"}

# Block indexes must be canonical base-10 integers. Python's int() also
# accepts "1_0", " 1 ", and "+1", which would let distinct-looking keys
# silently collide or map to surprising blocks.
_BLOCK_INDEX_PATTERN = re.compile(r"-?\d+")

_UNMAPPABLE = (
    "The confirmed structure cannot be confidently mapped onto this document's "
    "content streams — rebuild it as an accessible HTML working copy instead."
)


def _strip_whitespace(text: str) -> str:
    """Comparison key: extract_text synthesizes spaces from kerning offsets the
    raw operands do not contain, so ALL whitespace is removed before matching."""
    return "".join(text.split())


def _run_text(operands: list[Any], operator: bytes) -> str:
    if operator == b"Tj" or operator == b"'":
        return str(operands[0]) if operands else ""
    if operator == b"TJ":
        items = operands[0] if operands else []
        return "".join(str(item) for item in items if not isinstance(item, (int, float)))
    # The '"' operator is (aw, ac, string).
    return str(operands[2]) if len(operands) >= 3 else ""


def _segment_page(operations: list[tuple[list[Any], bytes]]) -> tuple[list[tuple[list[Any], bytes]], list[str]]:
    """Wrap each text-showing run (its buffered positioning ops through the show
    op) in /P << /MCID i >> BDC ... EMC. Returns (new_operations, run_texts)."""
    new_ops: list[tuple[list[Any], bytes]] = []
    pending: list[tuple[list[Any], bytes]] = []
    run_texts: list[str] = []
    for operands, operator in operations:
        if operator in _RUN_START_OPS:
            new_ops.extend(pending)
            pending = [(operands, operator)]
        elif operator in _TEXT_SHOW_OPS:
            mcid = len(run_texts)
            new_ops.append((
                [NameObject("/P"), DictionaryObject({NameObject("/MCID"): NumberObject(mcid)})],
                b"BDC",
            ))
            new_ops.extend(pending)
            pending = []
            new_ops.append((operands, operator))
            new_ops.append(([], b"EMC"))
            run_texts.append(_run_text(operands, operator))
        else:
            new_ops.extend(pending)
            pending = []
            new_ops.append((operands, operator))
    new_ops.extend(pending)
    return new_ops, run_texts


def _validate_roles(confirmed_roles: dict[str, str] | None) -> dict[int, str]:
    if confirmed_roles is not None and not isinstance(confirmed_roles, dict):
        raise RemediationError(
            "Confirmed structure roles must be a mapping of block index to role."
        )
    if not confirmed_roles:
        raise RemediationError(
            "No confirmed structure roles were supplied; a human must confirm each block's role first."
        )
    roles: dict[int, str] = {}
    for key, value in confirmed_roles.items():
        if not isinstance(value, str) or value not in ALLOWED_ROLES:
            raise RemediationError(
                f"Role '{value}' is not supported; confirmed roles must be one of h1, h2, h3, p, li."
            )
        if not _BLOCK_INDEX_PATTERN.fullmatch(str(key)):
            raise RemediationError(f"Block index '{key}' is not a valid block index.")
        index = int(str(key))
        if index in roles:
            # Two keys normalized to the same block ("1" and 1). Which one wins
            # would be dict-order luck, so conflicting confirmations decline.
            raise RemediationError(
                f"Block index {index} was confirmed more than once; resolve the "
                "conflicting confirmations and try again."
            )
        roles[index] = value
    return roles


def _validate_reading_order(reading_order: Any, block_count: int) -> list[int]:
    """A reading order is applied only when it is unambiguously a permutation
    of the matched block indexes: a real sequence of real integers. Strings,
    mappings, floats, and booleans are declined rather than coerced — silently
    reinterpreting a malformed order would apply structure the human never
    confirmed."""
    invalid = RemediationError(
        "The reading order must be a permutation of the matched block indexes; it was not applied."
    )
    if not isinstance(reading_order, (list, tuple)):
        raise invalid
    if any(isinstance(index, bool) or not isinstance(index, int) for index in reading_order):
        raise invalid
    order = [int(index) for index in reading_order]
    if sorted(order) != list(range(block_count)):
        raise invalid
    return order


def _build_confirmed_tag_tree(input_data: dict[str, Any]) -> dict[str, Any]:
    payload: bytes = input_data["payload"]
    roles = _validate_roles(input_data.get("confirmed_roles"))
    reading_order = input_data.get("reading_order")

    try:
        reader = PdfReader(io.BytesIO(payload), strict=False)
    except Exception as error:
        raise RemediationError(f"The PDF could not be parsed for remediation: {type(error).__name__}") from error
    if reader.is_encrypted:
        raise RemediationError("Encrypted PDFs are not remediated; request an unencrypted source copy.")

    root = reader.trailer.get("/Root", {})
    try:
        root = root.get_object()
    except AttributeError:
        pass
    if (root or {}).get("/StructTreeRoot") is not None:
        raise RemediationError(
            "This PDF already carries a structure tree; review it instead of rebuilding. "
            "Rebuilding over existing tags could destroy structure a human already authored."
        )

    # Recorded BEFORE any mutation; the anti-vandal check compares against these.
    source_page_texts = [page.extract_text() or "" for page in reader.pages]
    try:
        blocks = extract_blocks(payload)
    except DerivationError as error:
        raise RemediationError(str(error)) from error

    if any(index < 0 or index >= len(blocks) for index in roles):
        raise RemediationError(_UNMAPPABLE)

    writer = PdfWriter(clone_from=reader)

    # Segment every page's content stream into text runs and wrap each run in
    # marked content. MCIDs restart at 0 on each page; the global run order
    # (page order, run order within page) is the shared block index space.
    run_texts: list[str] = []
    run_locations: list[tuple[Any, int]] = []  # block index -> (page, mcid)
    per_page_run_counts: list[int] = []
    for page in writer.pages:
        contents = page.get("/Contents")
        if contents is None:
            per_page_run_counts.append(0)
            continue
        stream = ContentStream(contents.get_object(), writer)
        if any(operator in _MARKED_CONTENT_OPS for _, operator in stream.operations):
            raise RemediationError(
                "This PDF already carries marked-content operators; review the existing "
                "tagging instead of rebuilding over it."
            )
        new_operations, page_runs = _segment_page(stream.operations)
        per_page_run_counts.append(len(page_runs))
        if not page_runs:
            continue
        for mcid, text in enumerate(page_runs):
            run_texts.append(text)
            run_locations.append((page, mcid))
        stream.operations = new_operations
        page.replace_contents(stream)

    # Every confirmed block must map 1:1 onto a content run: identical counts
    # and per-index text equality after stripping all whitespace. Anything less
    # would make MCID-to-role assignment a guess, so the tool declines.
    if len(run_texts) != len(blocks):
        raise RemediationError(_UNMAPPABLE)
    if any(_strip_whitespace(run) != _strip_whitespace(block) for run, block in zip(run_texts, blocks)):
        raise RemediationError(_UNMAPPABLE)

    if reading_order is not None:
        order = _validate_reading_order(reading_order, len(blocks))
    else:
        order = list(range(len(blocks)))

    # Structure tree: StructTreeRoot -> Document -> H1/H2/H3/P leaves, with
    # consecutive li blocks (in logical order) grouped under one /L as
    # /L -> /LI -> /LBody. Leaves carry /K = MCID and /Pg = their page.
    struct_root = DictionaryObject()
    struct_root_ref = writer._add_object(struct_root)
    document_elem = DictionaryObject({
        NameObject("/Type"): NameObject("/StructElem"),
        NameObject("/S"): NameObject("/Document"),
        NameObject("/P"): struct_root_ref,
    })
    document_ref = writer._add_object(document_elem)

    # ParentTree slots: one sequential /StructParents key per page with runs.
    page_slots: dict[int, tuple[int, list[Any]]] = {}
    next_key = 0
    for page_index, page in enumerate(writer.pages):
        count = per_page_run_counts[page_index]
        if count:
            page[NameObject("/StructParents")] = NumberObject(next_key)
            page_slots[id(page)] = (next_key, [None] * count)
            next_key += 1

    def make_leaf(tag: str, parent_ref: Any, block_index: int) -> Any:
        page, mcid = run_locations[block_index]
        element = DictionaryObject({
            NameObject("/Type"): NameObject("/StructElem"),
            NameObject("/S"): NameObject(f"/{tag}"),
            NameObject("/P"): parent_ref,
            NameObject("/K"): NumberObject(mcid),
            NameObject("/Pg"): page.indirect_reference,
        })
        reference = writer._add_object(element)
        page_slots[id(page)][1][mcid] = reference
        return reference

    document_kids = ArrayObject()
    headings = list_items = 0
    position = 0
    while position < len(order):
        block_index = order[position]
        role = roles.get(block_index, "p")
        if role == "li":
            list_elem = DictionaryObject({
                NameObject("/Type"): NameObject("/StructElem"),
                NameObject("/S"): NameObject("/L"),
                NameObject("/P"): document_ref,
            })
            list_ref = writer._add_object(list_elem)
            list_kids = ArrayObject()
            while position < len(order) and roles.get(order[position], "p") == "li":
                item_block = order[position]
                item_elem = DictionaryObject({
                    NameObject("/Type"): NameObject("/StructElem"),
                    NameObject("/S"): NameObject("/LI"),
                    NameObject("/P"): list_ref,
                })
                item_ref = writer._add_object(item_elem)
                body_ref = make_leaf("LBody", item_ref, item_block)
                item_elem[NameObject("/K")] = ArrayObject([body_ref])
                list_kids.append(item_ref)
                list_items += 1
                position += 1
            list_elem[NameObject("/K")] = list_kids
            document_kids.append(list_ref)
        else:
            if role in {"h1", "h2", "h3"}:
                headings += 1
            document_kids.append(make_leaf(_ROLE_TO_TAG[role], document_ref, block_index))
            position += 1
    document_elem[NameObject("/K")] = document_kids

    nums = ArrayObject()
    for page in writer.pages:
        entry = page_slots.get(id(page))
        if entry is not None:
            key, slots = entry
            nums.append(NumberObject(key))
            nums.append(writer._add_object(ArrayObject(slots)))
    struct_root.update({
        NameObject("/Type"): NameObject("/StructTreeRoot"),
        NameObject("/K"): ArrayObject([document_ref]),
        NameObject("/ParentTree"): writer._add_object(DictionaryObject({NameObject("/Nums"): nums})),
        NameObject("/ParentTreeNextKey"): NumberObject(len(page_slots)),
    })
    writer_root = writer.root_object
    writer_root[NameObject("/StructTreeRoot")] = struct_root_ref
    writer_root[NameObject("/MarkInfo")] = DictionaryObject({NameObject("/Marked"): BooleanObject(True)})

    output = io.BytesIO()
    writer.write(output)
    remediated = output.getvalue()

    # ANTI-VANDAL CONTRACT: re-open the output with a fresh parser and prove the
    # mutation was purely additive — identical page count, identical per-page
    # extracted text. Assert, do not trust; on any mismatch, no output leaves.
    pages_preserved = text_preserved = False
    try:
        verifier = PdfReader(io.BytesIO(remediated), strict=False)
        pages_preserved = len(verifier.pages) == len(source_page_texts)
        if pages_preserved:
            text_preserved = all(
                (page.extract_text() or "") == source_page_texts[index]
                for index, page in enumerate(verifier.pages)
            )
    except Exception:
        pages_preserved = text_preserved = False
    if not (pages_preserved and text_preserved):
        raise RemediationError(
            "Verification failed: the rebuilt copy did not preserve the source page count "
            "and text exactly, so no output was produced. Rebuild the document as an "
            "accessible HTML working copy instead."
        )

    return {
        "actions": [{
            "rule_id": "PDF.STRUCTURE.SEMANTICS",
            "action": "build_confirmed_tag_tree",
            "provenance": "user_confirmed",
            "counts": {
                "blocks_tagged": len(blocks),
                "headings": headings,
                "list_items": list_items,
            },
            "reading_order_applied": reading_order is not None,
            "detail": (
                "Wrapped each text run in marked content and built a structure tree "
                "(StructTreeRoot/Document with human-confirmed heading, paragraph, and "
                "list roles) wired to MCIDs through the ParentTree. Only text content "
                "was tagged."
            ),
        }],
        "verification": {"text_preserved": True, "pages_preserved": True},
        "source_sha256": f"sha256:{sha256(payload).hexdigest()}",
        "remediated_sha256": f"sha256:{sha256(remediated).hexdigest()}",
        "source_bytes": len(payload),
        "remediated_bytes": len(remediated),
        "remediated_payload": remediated,
    }


class StructureRemediation:
    """Builds a tag tree in a PDF copy from human-confirmed block roles."""

    CONTRACT_VERSION = "tina-remediation-report/v1"
    CLAIM_BOUNDARY = (
        "Building tags from human-confirmed roles removes a technical barrier. "
        "Whether the resulting structure conveys the right meaning remains a "
        "human judgment, and no conformance is implied."
    )

    def __init__(self, gateway: ToolGateway) -> None:
        self.gateway = gateway

    @classmethod
    def with_builtin_tools(cls) -> "StructureRemediation":
        gateway = ToolGateway()
        gateway.register(
            ToolManifest(
                name="build_confirmed_tag_tree",
                version="1.0.0",
                purpose="Build a marked-content tag tree in a PDF copy from human-confirmed block roles.",
                deterministic=True,
                mutates_document=True,
                permissions=(REMEDIATE_STRUCTURE_PERMISSION,),
                timeout_ms=60_000,
            ),
            _build_confirmed_tag_tree,
        )
        return cls(gateway)

    def apply(
        self,
        filename: str,
        payload: bytes,
        confirmed_roles: dict[str, str],
        reading_order: list[int] | None = None,
    ) -> tuple[bytes, dict[str, Any]]:
        """Build the confirmed tag tree in an in-memory copy; return (new bytes, report)."""
        execution = self.gateway.execute(
            "build_confirmed_tag_tree",
            {"payload": payload, "confirmed_roles": confirmed_roles, "reading_order": reading_order},
            {REMEDIATE_STRUCTURE_PERMISSION},
        )
        remediated: bytes = execution["output"].pop("remediated_payload")
        report = {
            "contract_version": self.CONTRACT_VERSION,
            "claim_boundary": self.CLAIM_BOUNDARY,
            "filename": filename,
            "tool": execution["tool"],
            "tool_version": execution["tool_version"],
            "deterministic": execution["deterministic"],
            "mutates_document": execution["mutates_document"],
            **execution["output"],
        }
        return remediated, report
