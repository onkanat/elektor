import os
import math
import re
from pathlib import Path
from dataclasses import dataclass
from typing import Union, Optional, List, Tuple
import fitz  # PyMuPDF


try:
    from tests.e2e.conftest import FigureCrop
except (ImportError, AttributeError):
    @dataclass
    class FigureCrop:
        crop_id: str                              # Unique identifier (e.g. 'p15_fig_1')
        page_number: int                          # 1-indexed page number
        bbox: tuple[float, float, float, float]   # (x0, y0, x1, y1) in PDF points
        image_path: str                           # Saved PNG crop path
        caption: str                              # Associated caption or heading
        crop_type: str                            # 'diagram', 'schematic', 'chart', 'drawing'

# Ensure FigureCrop has dictionary compatibility and property helpers
if not hasattr(FigureCrop, "id"):
    FigureCrop.id = property(lambda self: self.crop_id)
if not hasattr(FigureCrop, "type"):
    FigureCrop.type = property(lambda self: self.crop_type)
if not hasattr(FigureCrop, "context"):
    FigureCrop.context = property(lambda self: self.caption)
if not hasattr(FigureCrop, "__getitem__"):
    def _crop_getitem(self, item: str):
        if item == "id":
            return self.crop_id
        if item == "type":
            return self.crop_type
        if item == "context":
            return self.caption
        if hasattr(self, item):
            return getattr(self, item)
        raise KeyError(item)
    FigureCrop.__getitem__ = _crop_getitem
if not hasattr(FigureCrop, "get"):
    def _crop_get(self, item: str, default=None):
        if item == "id":
            return self.crop_id
        if item == "type":
            return self.crop_type
        if item == "context":
            return self.caption
        return getattr(self, item, default)
    FigureCrop.get = _crop_get



class DocumentLayoutAnalyzer:
    def __init__(self, output_img_dir="downloads/extracted_images"):
        self.output_img_dir = Path(output_img_dir)
        self.output_img_dir.mkdir(parents=True, exist_ok=True)

    def analyze_page(
        self,
        page: Union[fitz.Page, str],
        table_masks: Optional[Union[List[Tuple[float, float, float, float]], int]] = None,
        **kwargs
    ) -> List[FigureCrop]:
        """
        Extracts complete, unfragmented figures while excluding table masks and shaded text blocks.
        Conforms to PROJECT.md:108-116.
        Also supports legacy analyze_page(pdf_path, page_number) invocation.
        """
        if isinstance(table_masks, int):
            # Legacy invocation: analyze_page(pdf_path, page_number)
            pdf_path = str(page)
            page_number = table_masks
            table_masks_list = kwargs.get("table_masks") or []
            doc = fitz.open(pdf_path)
            if page_number < 0 or page_number >= len(doc):
                doc.close()
                return []
            fitz_page = doc[page_number]
            crops = self._analyze_fitz_page(fitz_page, table_masks_list)
            doc.close()
            return crops

        if isinstance(page, str):
            pdf_path = page
            page_number = kwargs.get("page_number", 0)
            table_masks_list = table_masks if isinstance(table_masks, list) else []
            doc = fitz.open(pdf_path)
            if page_number < 0 or page_number >= len(doc):
                doc.close()
                return []
            fitz_page = doc[page_number]
            crops = self._analyze_fitz_page(fitz_page, table_masks_list)
            doc.close()
            return crops

        return self._analyze_fitz_page(page, table_masks or [])

    def _analyze_fitz_page(
        self,
        page: fitz.Page,
        table_masks: List[Tuple[float, float, float, float]]
    ) -> List[FigureCrop]:
        self.output_img_dir.mkdir(parents=True, exist_ok=True)
        page_w = page.rect.width
        page_h = page.rect.height
        page_area = page_w * page_h
        raw_drawings = page.get_drawings()
        candidates: List[FigureCrop] = []

        # Feature 6: Table Negative Masking & Margin Filtering
        expanded_masks: List[fitz.Rect] = []
        for m in (table_masks or []):
            if len(m) >= 4:
                mx0 = min(m[0], m[2]) - 1.5
                my0 = min(m[1], m[3]) - 1.5
                mx1 = max(m[0], m[2]) + 1.5
                my1 = max(m[1], m[3]) + 1.5
                if mx1 > mx0 and my1 > my0:
                    expanded_masks.append(fitz.Rect(mx0, my0, mx1, my1))

        filtered_drawings = []
        for draw in raw_drawings:
            rect = draw.get("rect")
            if not rect:
                continue
            rx0 = min(rect.x0, rect.x1)
            ry0 = min(rect.y0, rect.y1)
            rx1 = max(rect.x0, rect.x1, rx0 + 1.0)
            ry1 = max(rect.y0, rect.y1, ry0 + 1.0)
            r_norm = fitz.Rect(rx0, ry0, rx1, ry1)

            # Strip running headers and footers margin strokes
            if r_norm.y0 <= 50.0 or r_norm.y1 >= page_h - 50.0:
                continue

            in_table = False
            for m_rect in expanded_masks:
                if r_norm.intersects(m_rect) or (r_norm in m_rect):
                    in_table = True
                    break
            if not in_table:
                filtered_drawings.append(draw)

        if not filtered_drawings:
            return []

        # Normalize rects so zero-width/height lines are valid non-empty Rects
        rects: List[fitz.Rect] = []
        for d in filtered_drawings:
            r = d.get("rect")
            if r:
                rx0 = min(r.x0, r.x1)
                ry0 = min(r.y0, r.y1)
                rx1 = max(r.x0, r.x1, rx0 + 1.0)
                ry1 = max(r.y0, r.y1, ry0 + 1.0)
                rect_obj = fitz.Rect(rx0, ry0, rx1, ry1)
                # Ignore off-page drawing paths completely
                if not rect_obj.intersects(page.rect):
                    continue
                # Feature 9: Exclude full-page borders before connected component merging
                if (rect_obj.width * rect_obj.height) <= (0.85 * page_area):
                    rects.append(rect_obj)

        if not rects:
            return []

        merged = self._merge_rects(rects, threshold=30.0)

        for idx, m_rect in enumerate(merged):
            w = m_rect.width
            h = m_rect.height
            area = w * h

            # Feature 9: Aspect Ratio, Dimension & Density Filters
            # Reject full-page borders (>85% page area) and microscopic shapes (<2000 pt^2)
            if area > (0.85 * page_area) or area < 2000.0:
                continue
            aspect = w / h if h > 0 else 0
            if aspect > 20.0 or aspect < 0.05:
                continue

            # Feature 7: Drawing Path Clustering & Code Box Rejection
            internal_paths = sum(1 for r in rects if m_rect.intersects(r) or (r in m_rect))

            # Reject isolated divider lines / crossing hairlines with low path count (< 4 paths)
            if internal_paths < 4:
                continue

            # Reject full-page decorative perimeter frames (< 20 internal paths spanning > 80% width and height)
            if (w > 0.80 * page_w and h > 0.80 * page_h) and internal_paths < 20:
                continue

            # Shaded code box and multiline text frame check:
            # If < 20 paths and has multiline text (> 10 words), reject
            words_inside = [
                w_item for w_item in page.get_text("words")
                if fitz.Rect(w_item[:4]) in m_rect or m_rect.intersects(fitz.Rect(w_item[:4]))
            ]
            if internal_paths < 20 and len(words_inside) > 10:
                continue

            # Feature 8: Boundary Expansion for Arrowheads & Labels
            # Absorb adjacent text words within 15 pt (skip wide running body paragraphs)
            expanded_rect = fitz.Rect(m_rect)
            for w_item in page.get_text("words"):
                w_rect = fitz.Rect(w_item[:4])
                dist = self._rect_distance(m_rect, w_rect)
                if dist <= 15.0:
                    if w_rect.width < (0.65 * page_w):
                        expanded_rect = expanded_rect | w_rect

            # Add 8pt safety padding and clamp to page rect
            final_rect = (expanded_rect + (-8, -8, 8, 8)) & page.rect
            if final_rect.is_empty or final_rect.width <= 0 or final_rect.height <= 0:
                continue

            crop_id = f"p{page.number + 1}_fig_{idx+1}"
            crop_path = self.output_img_dir / f"{crop_id}.png"

            # Render 2x resolution crop
            mat = fitz.Matrix(2, 2)
            try:
                pix = page.get_pixmap(matrix=mat, clip=final_rect)
                pix.save(str(crop_path))
            except Exception:
                pix = page.get_pixmap(clip=final_rect)
                pix.save(str(crop_path))

            # Detect figure caption if present
            fig_caption = f"Figure {idx+1}"
            for block in page.get_text("blocks"):
                b_text = block[4].strip()
                if re.search(r"(?i)(?:Figure|Şekil)\s+(\d+)", b_text):
                    b_rect = fitz.Rect(block[:4])
                    if self._rect_distance(final_rect, b_rect) < 60.0:
                        fig_caption = b_text.split("\n")[0].strip()
                        break

            candidates.append(FigureCrop(
                crop_id=crop_id,
                page_number=page.number + 1,
                bbox=(final_rect.x0, final_rect.y0, final_rect.x1, final_rect.y1),
                image_path=str(crop_path),
                caption=fig_caption,
                crop_type="diagram" if internal_paths >= 20 else "drawing"
            ))

        # Feature 10: Non-Overlapping Figure Deduplication (IoU / Non-Maximum Suppression)
        return self._deduplicate_crops(candidates)

    def _merge_rects(self, rects: List[fitz.Rect], threshold: float = 30.0) -> List[fitz.Rect]:
        if not rects:
            return []
        merged: List[fitz.Rect] = []
        remaining = list(rects)
        while remaining:
            curr = remaining.pop(0)
            i = 0
            while i < len(remaining):
                test = remaining[i]
                if curr.intersects(test) or self._rect_distance(curr, test) < threshold:
                    curr = curr | test
                    remaining.pop(i)
                    i = 0
                else:
                    i += 1
            merged.append(curr)
        return merged

    def _rect_distance(self, r1: fitz.Rect, r2: fitz.Rect) -> float:
        x_dist = max(0.0, max(r1.x0, r2.x0) - min(r1.x1, r2.x1))
        y_dist = max(0.0, max(r1.y0, r2.y0) - min(r1.y1, r2.y1))
        return math.sqrt(x_dist**2 + y_dist**2)

    def _deduplicate_crops(self, crops: List[FigureCrop]) -> List[FigureCrop]:
        if len(crops) <= 1:
            return crops
        sorted_crops = sorted(
            crops,
            key=lambda c: (fitz.Rect(*c.bbox).width * fitz.Rect(*c.bbox).height),
            reverse=True
        )
        kept: List[FigureCrop] = []
        for c in sorted_crops:
            r = fitz.Rect(*c.bbox)
            suppressed = False
            for k in kept:
                rk = fitz.Rect(*k.bbox)
                inter = r & rk
                if inter.is_valid and not inter.is_empty:
                    inter_area = inter.width * inter.height
                    r_area = r.width * r.height
                    rk_area = rk.width * rk.height
                    union_area = r_area + rk_area - inter_area
                    iou = inter_area / union_area if union_area > 0 else 0
                    if iou > 0.60 or (r_area > 0 and (inter_area / r_area) > 0.85):
                        suppressed = True
                        break
            if not suppressed:
                kept.append(c)
        return kept
