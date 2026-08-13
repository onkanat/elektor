import os
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional
try:
    from PIL import Image
except ImportError:
    Image = None

class ImageOptimizer:
    """Handles image compression, resizing (WebP 85% quality, max 1024px),

    and safe raw crop cleanup for FAZ-11 Multimodal Visual Datasets.
    """

    def __init__(self, max_dimension: int = 1024, webp_quality: int = 85):
        self.max_dimension = max_dimension
        self.webp_quality = webp_quality

    def optimize_image(self, input_path: Path, output_dir: Path) -> Optional[Path]:
        """Compresses and resizes a raw image into WebP format preserving aspect ratio.

        Returns output WebP path on success, or None on failure.
        """
        if not input_path.exists() or not input_path.is_file():
            return None

        if Image is None:
            # Fallback if Pillow is not installed: copy raw file
            output_dir.mkdir(parents=True, exist_ok=True)
            target_path = output_dir / input_path.name
            shutil.copy2(input_path, target_path)
            return target_path

        output_dir.mkdir(parents=True, exist_ok=True)
        webp_name = f"{input_path.stem}.webp"
        output_path = output_dir / webp_name

        try:
            with Image.open(input_path) as img:
                # Convert RGBA / P modes to RGB for WebP compatibility
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")

                # Resize if dimensions exceed max_dimension
                width, height = img.size
                if width > self.max_dimension or height > self.max_dimension:
                    if width >= height:
                        new_width = self.max_dimension
                        new_height = int(height * (self.max_dimension / float(width)))
                    else:
                        new_height = self.max_dimension
                        new_width = int(width * (self.max_dimension / float(height)))
                    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

                # Save as optimized WebP
                img.save(output_path, "WEBP", quality=self.webp_quality, optimize=True)
                return output_path
        except Exception as e:
            print(f"Warning: Failed to optimize image {input_path.name} to WebP: {e}")
            # Fallback to direct copy if PIL fails
            fallback_path = output_dir / input_path.name
            shutil.copy2(input_path, fallback_path)
            return fallback_path

    def process_raw_images(self, raw_images_dir: Path, target_images_dir: Path) -> List[Dict[str, Any]]:
        """Processes all raw images in raw_images_dir, converts them to WebP in target_images_dir,

        and returns a list of mapping records.
        """
        if not raw_images_dir.exists():
            return []

        processed_images = []
        raw_files = [f for f in raw_images_dir.glob("*") if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp", ".webp")]

        for raw_file in raw_files:
            webp_path = self.optimize_image(raw_file, target_images_dir)
            if webp_path:
                original_size = raw_file.stat().st_size
                optimized_size = webp_path.stat().st_size
                saved_ratio = round((1 - (optimized_size / max(1, original_size))) * 100, 1)

                processed_images.append({
                    "raw_filename": raw_file.name,
                    "raw_path": str(raw_file),
                    "webp_filename": webp_path.name,
                    "webp_path": str(webp_path),
                    "relative_image_path": f"images/{webp_path.name}",
                    "original_bytes": original_size,
                    "optimized_bytes": optimized_size,
                    "saved_ratio_percent": saved_ratio
                })

        return processed_images

    def cleanup_raw_images(self, raw_images_dir: Path, verified_mappings: List[Dict[str, Any]]) -> int:
        """Deletes raw PNG files from raw_images_dir if they have been safely converted to WebP."""
        cleaned_count = 0
        for item in verified_mappings:
            raw_path = Path(item.get("raw_path", ""))
            webp_path = Path(item.get("webp_path", ""))

            if raw_path.exists() and webp_path.exists() and webp_path.stat().st_size > 0:
                try:
                    raw_path.unlink()
                    cleaned_count += 1
                except Exception as e:
                    print(f"Warning: Could not remove raw crop {raw_path.name}: {e}")

        return cleaned_count
