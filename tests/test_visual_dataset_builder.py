import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from pipeline.visual_dataset_builder import VisualDatasetBuilder

def test_visual_dataset_builder_skips_invalid_descriptions(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text('{"project_id": "test_vis_unit", "model_vision": "deepseek-ocr:3b-bf16"}', encoding="utf-8")

    builder = VisualDatasetBuilder(config_path=str(config_path))
    
    # Mock optimizer and vision manager
    builder.optimizer.process_raw_images = MagicMock(return_value=[
        {
            "raw_filename": "test1.png",
            "raw_path": str(tmp_path / "test1.png"),
            "webp_filename": "test1.webp",
            "webp_path": str(tmp_path / "test1.webp"),
            "relative_image_path": "images/test1.webp",
            "original_bytes": 100,
            "optimized_bytes": 50,
            "saved_ratio_percent": 50.0
        }
    ])

    # Case 1: Vision model returns invalid/error description
    with patch("pipeline.visual_dataset_builder.VisionOCRManager") as MockVision:
        instance = MockVision.return_value
        instance.describe_cropped_image.return_value = "Technical schematic and architectural diagram representation (test1)"
        
        (tmp_path / "test1.webp").write_text("fake_image_content")
        builder.raw_images_dir = tmp_path
        builder.export_dir = tmp_path / "exports"
        builder.export_images_dir = builder.export_dir / "images"

        res = builder.export_multimodal_dataset(clean_raw_crops=False)
        assert res["status"] == "error"
        assert res["exported_records"] == 0
        assert res["failed_crops"] == 1

def test_visual_dataset_builder_preserves_raw_crops_by_default(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text('{"project_id": "test_vis_unit_2", "model_vision": "deepseek-ocr:3b-bf16"}', encoding="utf-8")

    builder = VisualDatasetBuilder(config_path=str(config_path))
    builder.optimizer.cleanup_raw_images = MagicMock(return_value=1)
    builder.optimizer.process_raw_images = MagicMock(return_value=[
        {
            "raw_filename": "test2.png",
            "raw_path": str(tmp_path / "test2.png"),
            "webp_filename": "test2.webp",
            "webp_path": str(tmp_path / "test2.webp"),
            "relative_image_path": "images/test2.webp",
            "original_bytes": 100,
            "optimized_bytes": 50,
            "saved_ratio_percent": 50.0
        }
    ])

    with patch("pipeline.visual_dataset_builder.VisionOCRManager") as MockVision:
        instance = MockVision.return_value
        instance.describe_cropped_image.return_value = "Valid technical diagram showing resistor R1 connected to VCC."
        
        (tmp_path / "test2.webp").write_text("fake_image_content")
        builder.raw_images_dir = tmp_path
        builder.export_dir = tmp_path / "exports"
        builder.export_images_dir = builder.export_dir / "images"

        # Default clean_raw_crops=False -> cleanup_raw_images should NOT be called
        res = builder.export_multimodal_dataset(clean_raw_crops=False)
        assert res["status"] == "success"
        assert res["exported_records"] == 1
        builder.optimizer.cleanup_raw_images.assert_not_called()

        # Explicit clean_raw_crops=True -> cleanup_raw_images should be called
        res_clear = builder.export_multimodal_dataset(clean_raw_crops=True)
        assert res_clear["status"] == "success"
        builder.optimizer.cleanup_raw_images.assert_called_once()
