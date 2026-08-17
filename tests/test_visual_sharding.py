import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from pipeline.visual_dataset_builder import VisualDatasetBuilder

def test_visual_dataset_builder_quality_filter_25_chars(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text('{"project_id": "test_vis_quality", "model_vision": "deepseek-ocr:3b-bf16"}', encoding="utf-8")

    builder = VisualDatasetBuilder(config_path=str(config_path))
    builder.optimizer.process_raw_images = MagicMock(return_value=[
        {
            "raw_filename": "short.png",
            "raw_path": str(tmp_path / "short.png"),
            "webp_filename": "short.webp",
            "webp_path": str(tmp_path / "short.webp"),
            "relative_image_path": "images/short.webp",
            "original_bytes": 100,
            "optimized_bytes": 50,
            "saved_ratio_percent": 50.0
        }
    ])

    with patch("pipeline.visual_dataset_builder.VisionOCRManager") as MockVision:
        instance = MockVision.return_value
        instance.check_health.return_value = True
        # Less than 25 chars -> quality filter should reject
        instance.describe_cropped_image.return_value = "Short text (15ch)"
        
        (tmp_path / "short.webp").write_text("fake_image_content")
        builder.raw_images_dir = tmp_path
        builder.export_dir = tmp_path / "exports"
        builder.export_images_dir = builder.export_dir / "images"

        res = builder.export_multimodal_dataset(clean_raw_crops=False, min_chars=25)
        assert res["status"] == "error"
        assert res["exported_records"] == 0
        assert res["low_quality_crops"] == 1

def test_visual_dataset_builder_parallel_sharding(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text('{"project_id": "test_vis_shard", "model_vision": "deepseek-ocr:3b-bf16"}', encoding="utf-8")

    builder = VisualDatasetBuilder(config_path=str(config_path))
    builder.optimizer.process_raw_images = MagicMock(return_value=[
        {
            "raw_filename": f"img_{i}.png",
            "raw_path": str(tmp_path / f"img_{i}.png"),
            "webp_filename": f"img_{i}.webp",
            "webp_path": str(tmp_path / f"img_{i}.webp"),
            "relative_image_path": f"images/img_{i}.webp",
            "original_bytes": 100,
            "optimized_bytes": 50,
            "saved_ratio_percent": 50.0
        } for i in range(4)
    ])

    with patch("pipeline.visual_dataset_builder.VisionOCRManager") as MockVision:
        instance = MockVision.return_value
        instance.check_health.return_value = True
        instance.describe_cropped_image.return_value = "Valid technical diagram with detailed component description and pinouts."
        
        for i in range(4):
            (tmp_path / f"img_{i}.webp").write_text("fake_image_content")

        builder.raw_images_dir = tmp_path
        builder.export_dir = tmp_path / "exports"
        builder.export_images_dir = builder.export_dir / "images"

        res = builder.export_multimodal_dataset(clean_raw_crops=False, shards=2, shard_ports="11434,11435")
        assert res["status"] == "success"
        assert res["exported_records"] == 4
