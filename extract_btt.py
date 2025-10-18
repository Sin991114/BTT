import argparse
import json
import os
import re
import sys
from typing import Dict, List, Tuple


def read_pdf_text(path: str) -> str:
    try:
        import pdfplumber  # type: ignore

        parts = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                parts.append(page.extract_text() or "")
        return "\n".join(parts)
    except Exception:
        try:
            from PyPDF2 import PdfReader  # type: ignore

            reader = PdfReader(path)
            parts = []
            for page in reader.pages:
                text = page.extract_text() or ""
                parts.append(text)
            return "\n".join(parts)
        except Exception as e:
            raise RuntimeError(
                "Failed to read PDF. Install pdfplumber or PyPDF2 (e.g. `pip install pdfplumber`)."
            ) from e


def normalize_space(s: str) -> str:
    s = re.sub(r"[ \t\u00A0]+", " ", s)
    s = re.sub(r"\s*\n\s*", " ", s)
    return s.strip()


_QNUM_RE = re.compile(r"(?mi)^\s*(?:Q|Question)?\s*(\d{1,3})\s*[\.|\)]\s+")


def split_questions(raw: str):
    blocks = []
    it = list(_QNUM_RE.finditer(raw))
    for i, m in enumerate(it):
        start = m.end()
        end = it[i + 1].start() if i + 1 < len(it) else len(raw)
        qnum = int(m.group(1))
        blocks.append((qnum, raw[start:end]))
    return blocks


def _group_page_lines(page) -> List[dict]:
    words = page.extract_words(use_text_flow=True, keep_blank_chars=False)
    words.sort(key=lambda w: (round(w.get("top", 0), 1), w.get("x0", 0)))
    lines: List[dict] = []
    current = None
    tol = 2.0
    for w in words:
        top = float(w.get("top", 0))
        if current is None or abs(top - current["top"]) > tol:
            # start new line
            current = {
                "top": top,
                "bottom": float(w.get("bottom", top)),
                "x0": float(w.get("x0", 0)),
                "x1": float(w.get("x1", 0)),
                "texts": [w.get("text", "")],
            }
            lines.append(current)
        else:
            current["top"] = min(current["top"], top)
            current["bottom"] = max(current["bottom"], float(w.get("bottom", top)))
            current["x0"] = min(current["x0"], float(w.get("x0", 0)))
            current["x1"] = max(current["x1"], float(w.get("x1", 0)))
            current["texts"].append(w.get("text", ""))
    for ln in lines:
        ln["text"] = normalize_space(" ".join(ln.pop("texts", [])))
    return lines


def extract_question_images(pdf_path: str, out_dir: str) -> Dict[int, List[str]]:
    import pdfplumber  # type: ignore
    from PIL import Image  # type: ignore

    os.makedirs(out_dir, exist_ok=True)
    rel_base = os.path.relpath(out_dir, start=os.path.dirname(os.path.abspath(pdf_path)))

    images_by_q: Dict[int, List[str]] = {}
    with pdfplumber.open(pdf_path) as pdf:
        for pidx, page in enumerate(pdf.pages):
            page_w = page.width
            page_h = page.height
            lines = _group_page_lines(page)
            # find question anchors on this page
            anchors: List[Tuple[int, float]] = []  # (qnum, top)
            for ln in lines:
                m = re.match(r"^\s*(?:Q|Question)?\s*(\d{1,4})\s*[\.|\)]\s+", ln.get("text", ""), re.I)
                if m:
                    anchors.append((int(m.group(1)), float(ln["top"])))
            if not anchors:
                continue
            anchors.sort(key=lambda t: t[1])

            # build vertical ranges for each question on page
            ranges: List[Tuple[int, float, float]] = []  # (qnum, top, bottom)
            for i, (qnum, top) in enumerate(anchors):
                # include a padding above the anchor to capture graphics placed above the question text
                pad_up = 40.0
                pad_down = 10.0
                rtop = max(0.0, top - pad_up)
                bottom = anchors[i + 1][1] if i + 1 < len(anchors) else page_h
                rbot = min(page_h, bottom + pad_down)
                ranges.append((qnum, rtop, rbot))

            # Render the page once for cropping and general rasterization
            im_render = page.to_image(resolution=200).original  # PIL.Image
            scale_x = im_render.width / page_w
            scale_y = im_render.height / page_h

            # Strategy A: use embedded images if any, mapped into ranges
            p_images = getattr(page, "images", []) or []
            if p_images:
                for img_idx, img in enumerate(p_images):
                    x0 = float(img.get("x0", 0))
                    x1 = float(img.get("x1", 0))
                    top = float(img.get("top", 0))
                    bottom = float(img.get("bottom", 0))
                    w = max(0.0, x1 - x0)
                    h = max(0.0, bottom - top)
                    # skip tiny artifacts or full-page backgrounds
                    if w < 20 or h < 20:
                        continue
                    if w > page_w * 0.95 and h > page_h * 0.95:
                        continue

                    center_y = (top + bottom) / 2.0
                    # find the question range that contains this image center
                    matched_q = None
                    for (qnum, rtop, rbot) in ranges:
                        if center_y >= rtop and center_y <= rbot:
                            matched_q = qnum
                            break
                    if matched_q is None:
                        continue

                    crop_box = (
                        int(max(0, (x0 - 2) * scale_x)),
                        int(max(0, (top - 2) * scale_y)),
                        int(min(im_render.width, (x1 + 2) * scale_x)),
                        int(min(im_render.height, (bottom + 2) * scale_y)),
                    )
                    crop = im_render.crop(crop_box)
                    out_name = f"q{matched_q}_{len(images_by_q.get(matched_q, [])) + 1}.png"
                    out_path = os.path.join(out_dir, out_name)
                    crop.save(out_path)
                    rel_path = os.path.relpath(out_path, start=os.path.dirname(os.path.abspath(pdf_path)))
                    rel_path = rel_path.replace("\\", "/")
                    images_by_q.setdefault(matched_q, []).append(rel_path)

            # Strategy B: for questions with no embedded images, crop a left column of the question band.
            # This helps when signs are vector drawings (not embedded images).
            for (qnum, rtop, rbot) in ranges:
                # Skip if we already captured an image for this question from strategy A
                if images_by_q.get(qnum):
                    continue

                # lines within band
                band_lines = [ln for ln in lines if float(ln.get("top", 0)) >= rtop and float(ln.get("top", 0)) <= rbot]
                if not band_lines:
                    continue
                # find first option line and min x0 of text
                min_x0 = min(float(ln.get("x0", 0)) for ln in band_lines)
                optA = next((ln for ln in band_lines if re.match(r"^[\s\(]*[A1①][\)\.]?\s+", ln.get("text", ""), re.I)), None)
                band_top = rtop
                band_bottom = rbot
                if optA is not None:
                    # crop above the options block, where the sign typically is
                    band_bottom = float(optA.get("top", band_bottom))

                # Heuristic left column width and right column width
                left_w = max(80.0, min(min_x0 - 8.0, page_w * 0.42))
                right_x0 = max(min_x0 + 120.0, page_w * 0.5)  # right side beyond text area
                right_w = page_w - right_x0 - 10.0

                # Ensure reasonable band height
                if band_bottom - band_top < 40.0:
                    continue

                crops = []
                # Left column crop
                if left_w >= 60.0:
                    crops.append(
                        (
                            int(max(0, 0 * scale_x)),
                            int(max(0, band_top * scale_y)),
                            int(min(im_render.width, left_w * scale_x)),
                            int(min(im_render.height, band_bottom * scale_y)),
                        )
                    )
                # Right column crop
                if right_w >= 60.0:
                    crops.append(
                        (
                            int(max(0, right_x0 * scale_x)),
                            int(max(0, band_top * scale_y)),
                            int(min(im_render.width, (right_x0 + right_w) * scale_x)),
                            int(min(im_render.height, band_bottom * scale_y)),
                        )
                    )
                # Center-top block above options (useful if image is centered)
                center_x0 = max(0.0, min_x0 - 20.0)
                center_x1 = min(page_w, max(center_x0 + 120.0, page_w * 0.55))
                crops.append(
                    (
                        int(center_x0 * scale_x),
                        int(max(0, (band_top) * scale_y)),
                        int(min(im_render.width, center_x1 * scale_x)),
                        int(min(im_render.height, band_bottom * scale_y)),
                    )
                )

                for crop_box in crops:
                    if crop_box[2] - crop_box[0] < 40 or crop_box[3] - crop_box[1] < 40:
                        continue
                    crop = im_render.crop(crop_box)
                    # Skip nearly-empty crops (very dark or very uniform). Quick variance check.
                    try:
                        import numpy as _np  # type: ignore

                        arr = _np.array(crop.convert('L'))
                        if arr.var() < 200:  # too uniform; likely blank margin
                            continue
                    except Exception:
                        pass

                    out_name = f"q{qnum}_{len(images_by_q.get(qnum, [])) + 1}.png"
                    out_path = os.path.join(out_dir, out_name)
                    crop.save(out_path)
                    rel_path = os.path.relpath(out_path, start=os.path.dirname(os.path.abspath(pdf_path)))
                    rel_path = rel_path.replace("\\", "/")
                    images_by_q.setdefault(qnum, []).append(rel_path)
                    break  # keep one image per question for now

    return images_by_q


_OPT_LETTERS_RE = re.compile(
    r"(?ms)^[ \t]*([A-Da-d])\s*[\.|\)]\s*(.+?)(?=^[ \t]*[A-Da-d]\s*[\.|\)]\s*|\Z)",
)
_OPT_NUMBERS_RE = re.compile(
    r"(?ms)^[ \t]*(?:\(?([1-4])\)?|([①②③④]))\s*[\.|\)]?\s*(.+?)(?=^[ \t]*(?:\(?[1-4]\)?|[①②③④])\s*[\.|\)]?\s*|\Z)",
)


def parse_question_block(block_text: str):
    # Try to find the first option marker (A. / 1.) and split the stem before it
    letter_iter = list(_OPT_LETTERS_RE.finditer(block_text))
    number_iter = [] if letter_iter else list(_OPT_NUMBERS_RE.finditer(block_text))

    options = []
    stem = ""
    if letter_iter:
        first = letter_iter[0]
        stem = normalize_space(block_text[: first.start()])
        for m in letter_iter:
            txt = normalize_space(m.group(2))
            options.append(txt)
    elif number_iter:
        first = number_iter[0]
        stem = normalize_space(block_text[: first.start()])
        for m in number_iter:
            txt = normalize_space(m.group(3))
            options.append(txt)
    else:
        # No explicit options found; attempt a simple heuristic: split lines into 5 parts
        lines = [l.strip() for l in block_text.strip().splitlines() if l.strip()]
        if len(lines) >= 5:
            stem = normalize_space(" ".join(lines[:-4]))
            options = [normalize_space(x) for x in lines[-4:]]
        else:
            return None

    # Accept 3 or 4 options (some BTT sets have 3 options)
    if not stem or len(options) < 3:
        return None
    return stem, options[:4]


def parse_answers(raw: str):
    answers = {}
    lines = [ln.strip() for ln in raw.splitlines()]

    # Pattern 1: per-line mapping like "1. B" or "1) 2"
    for line in lines:
        if not line or re.match(r"^part\b", line, re.I):
            continue
        m = re.match(r"^(\d{1,4})\s*[\.|\)\-:]*\s*([A-Da-d1-4])\b", line)
        if m:
            qnum = int(m.group(1))
            val = m.group(2).upper()
            if val in {"A", "B", "C", "D"}:
                idx = ord(val) - ord("A")
            else:
                try:
                    idx = int(val) - 1
                except ValueError:
                    continue
            if 0 <= idx <= 3:
                answers[qnum] = idx

    # Pattern 2: range headers like "1~10" followed by a string of letters "ABBCCA..."
    i = 0
    while i < len(lines):
        ln = lines[i]
        rng = re.match(r"^(\d{1,4})\s*[~\-]\s*(\d{1,4})\s*$", ln)
        if rng and i + 1 < len(lines):
            start = int(rng.group(1))
            end = int(rng.group(2))
            seq = lines[i + 1].strip()
            # Some PDFs may insert spaces; remove non-letters
            seq_letters = re.sub(r"[^A-Da-d]", "", seq).upper()
            expected = end - start + 1
            if len(seq_letters) == expected:
                for offset, ch in enumerate(seq_letters):
                    idx = ord(ch) - ord("A")
                    if 0 <= idx <= 3:
                        answers[start + offset] = idx
                i += 2
                continue
        i += 1

    return answers


def main():
    ap = argparse.ArgumentParser(description="Extract BTT questions and answers from PDFs")
    ap.add_argument("--questions-pdf", default="BTT Question.pdf")
    ap.add_argument("--answers-pdf", default="BTT Answer.pdf")
    ap.add_argument("--out-questions", default="questions.json")
    ap.add_argument("--out-answers", default="answers.json")
    ap.add_argument("--answers-format", choices=["map", "array"], default="map")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    if not os.path.exists(args.questions_pdf):
        print(f"Questions PDF not found: {args.questions_pdf}", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(args.answers_pdf):
        print(f"Answers PDF not found: {args.answers_pdf}", file=sys.stderr)
        sys.exit(1)

    q_text = read_pdf_text(args.questions_pdf)
    a_text = read_pdf_text(args.answers_pdf)

    q_blocks = split_questions(q_text)
    ans_map = parse_answers(a_text)

    items = []
    written = 0
    for qnum, block in q_blocks:
        parsed = parse_question_block(block)
        if not parsed:
            continue
        stem, opts = parsed
        if qnum not in ans_map:
            continue
        # Keep 3-4 options only
        if len(opts) < 3:
            continue
        items.append({"id": qnum, "question": stem, "options": opts[:4]})
        written += 1
        if args.limit and written >= args.limit:
            break

    if not items:
        print("No questions parsed. Adjust regex heuristics or verify PDF format.", file=sys.stderr)
        sys.exit(2)

    # Attempt to extract per-question images using pdfplumber
    try:
        import pdfplumber  # type: ignore
        from PIL import Image  # type: ignore
    except Exception:
        pdfplumber = None  # type: ignore
        Image = None  # type: ignore

    if pdfplumber is not None:
        try:
            images_map = extract_question_images(args.questions_pdf, out_dir=os.path.join(os.path.dirname(args.out_questions), "assets", "images"))
        except Exception:
            images_map = {}
    else:
        images_map = {}

    # Attach image paths if available
    if images_map:
        for it in items:
            qid = it["id"]
            if qid in images_map and images_map[qid]:
                it["images"] = images_map[qid]

    # Write questions.json
    with open(args.out_questions, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

    # Write answers.json
    if args.answers_format == "array":
        arr = []
        for it in items:
            arr.append(int(ans_map.get(it["id"], 0)))
        with open(args.out_answers, "w", encoding="utf-8") as f:
            json.dump(arr, f, ensure_ascii=False, indent=2)
    else:
        amap = {str(it["id"]): int(ans_map[it["id"]]) for it in items if it["id"] in ans_map}
        with open(args.out_answers, "w", encoding="utf-8") as f:
            json.dump(amap, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(items)} questions to {args.out_questions}")
    print(f"Wrote answers to {args.out_answers} as {args.answers_format}")


if __name__ == "__main__":
    main()
