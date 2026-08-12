import os
import math
from pathlib import Path
import fitz  # PyMuPDF

class DocumentLayoutAnalyzer:
    def __init__(self, output_img_dir="downloads/extracted_images"):
        self.output_img_dir = Path(output_img_dir)
        self.output_img_dir.mkdir(parents=True, exist_ok=True)
        
    def analyze_page(self, pdf_path: str, page_number: int):
        """
        Analyzes a specific page in the PDF to find visual zones (drawings/images)
        and associated text context (captions).
        Returns a list of dictionaries with bounding boxes, types, and text context.
        """
        doc = fitz.open(pdf_path)
        if page_number >= len(doc):
            doc.close()
            return []
            
        page = doc[page_number]
        visual_elements = []
        
        # 1. Check for raster images
        image_list = page.get_images(full=True)
        for img_idx, img in enumerate(image_list):
            xref = img[0]
            rects = page.get_image_rects(xref)
            for rect in rects:
                if rect.width > 30 and rect.height > 30:
                    visual_elements.append({
                        "type": "image",
                        "bbox": (rect.x0, rect.y0, rect.x1, rect.y1),
                        "xref": xref,
                        "id": f"img_{page_number}_{img_idx}"
                    })
                
        # 2. Check for vector drawings (shapes, charts, lines)
        drawings = page.get_drawings()
        if drawings:
            drawing_rects = []
            page_area = page.rect.width * page.rect.height
            for draw in drawings:
                rect = draw.get("rect")
                if rect:
                    w, h = rect.width, rect.height
                    # Skip extremely thin divider lines, header/footer borders, and microscopic shapes
                    if w < 10 or h < 10:
                        continue
                    aspect = w / h if h > 0 else 0
                    if aspect > 15 or aspect < 0.06:  # Thin horizontal/vertical lines
                        continue
                    drawing_rects.append(rect)
            
            merged_rects = self._merge_rects(drawing_rects, threshold=30.0)
            page_w, page_h = page.rect.width, page.rect.height
            for d_idx, rect in enumerate(merged_rects):
                w, h = rect.width, rect.height
                area = w * h
                # Ignore full-page border boxes (>85% page area) or small icon boxes (<6400 px^2)
                if area > (0.85 * page_area) or area < 6400 or w < 80 or h < 80:
                    continue
                # Ignore thin outer boxes
                aspect = w / h if h > 0 else 0
                if aspect > 10 or aspect < 0.1:
                    continue
                    
                visual_elements.append({
                    "type": "drawing",
                    "bbox": (rect.x0, rect.y0, rect.x1, rect.y1),
                    "id": f"draw_{page_number}_{d_idx}"
                })

        # Remove duplicate/contained visual elements
        visual_elements = self._filter_contained_elements(visual_elements)
                    
        # 3. Associate adjacent text blocks (captions/labels)
        text_blocks = page.get_text("blocks")
        for element in visual_elements:
            element_rect = fitz.Rect(*element["bbox"])
            associated_text = []
            
            for block in text_blocks:
                bx0, by0, bx1, by1, btext, block_no, block_type = block
                block_rect = fitz.Rect(bx0, by0, bx1, by1)
                
                dist = self._rect_distance(element_rect, block_rect)
                if dist < 100.0:
                    clean_txt = btext.strip()
                    if clean_txt and clean_txt not in associated_text:
                        associated_text.append(clean_txt)
                    
            element["context"] = "\n".join(associated_text)
            
            # 4. Crop and save the visual zone as a PNG image for Vision model processing
            mat = fitz.Matrix(2, 2)  # 2x scale for higher quality OCR/VLM
            try:
                # Add 5px padding
                padded_rect = element_rect + (-5, -5, 5, 5)
                padded_rect = padded_rect & page.rect
                
                pix = page.get_pixmap(matrix=mat, clip=padded_rect)
                img_path = self.output_img_dir / f"{Path(pdf_path).stem}_p{page_number}_{element['id']}.png"
                pix.save(str(img_path))
                element["image_path"] = str(img_path)
            except Exception as e:
                print(f"Error rendering clip for {element['id']}: {e}")
                element["image_path"] = None
                
        doc.close()
        return visual_elements

    def _merge_rects(self, rects, threshold=40.0):
        if not rects:
            return []
        
        merged = []
        remaining = list(rects)
        
        while remaining:
            current = remaining.pop(0)
            i = 0
            while i < len(remaining):
                test = remaining[i]
                if current.intersects(test) or self._rect_distance(current, test) < threshold:
                    current = current | test
                    remaining.pop(i)
                    i = 0
                else:
                    i += 1
            merged.append(current)
        return merged

    def _rect_distance(self, r1, r2):
        x_dist = max(0, max(r1.x0, r2.x0) - min(r1.x1, r2.x1))
        y_dist = max(0, max(r1.y0, r2.y0) - min(r1.y1, r2.y1))
        return math.sqrt(x_dist**2 + y_dist**2)

    def _filter_contained_elements(self, elements):
        if len(elements) <= 1:
            return elements
            
        filtered = []
        for i, el1 in enumerate(elements):
            r1 = fitz.Rect(*el1["bbox"])
            contained = False
            for j, el2 in enumerate(elements):
                if i == j:
                    continue
                r2 = fitz.Rect(*el2["bbox"])
                # If r1 is substantially inside r2 (>85% area overlap), drop r1 in favor of outer container r2
                intersection = r1 & r2
                if intersection.is_valid and not intersection.is_empty:
                    overlap_area = intersection.width * intersection.height
                    r1_area = r1.width * r1.height
                    if r1_area > 0 and (overlap_area / r1_area) > 0.85 and (r2.width * r2.height > r1_area):
                        contained = True
                        break
            if not contained:
                filtered.append(el1)
        return filtered
