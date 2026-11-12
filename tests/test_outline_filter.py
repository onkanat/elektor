from pipeline.extractor import ArchiveExtractor


def _extractor(**overrides):
    cfg = {
        "input_mode": "folder",
        "input_path": "/tmp",
        "db_path": ":memory:",
        "qdrant_db_path": "/tmp/qdrant-outline-test",
        "ollama_url": "http://localhost:11434",
        "model_embedding": "nomic-embed-text:latest",
        "model_analyzer": "test-model",
        "chunk_size": 100,
        "chunk_overlap": 20,
        "ocr_threshold_chars": 10,
    }
    cfg.update(overrides)
    return ArchiveExtractor(config_dict=cfg)


def test_outline_defaults_keep_all_nodes():
    ex = _extractor()
    nodes = [
        {"title": "A", "page": 0, "depth": 0},
        {"title": "A.1", "page": 1, "depth": 1},
        {"title": "B", "page": 2, "depth": 0},
    ]
    segments = ex._build_outline_segments(nodes, total_pages=3)
    assert segments == [("A", 0, 0), ("A.1", 1, 1), ("B", 2, 2)]
    ex.close()


def test_outline_max_depth_keeps_top_level_chapters():
    ex = _extractor(outline_max_depth=0)
    nodes = [
        {"title": "Chapter 1", "page": 0, "depth": 0},
        {"title": "Chapter 1 - Intro", "page": 1, "depth": 1},
        {"title": "Chapter 1 - Details", "page": 2, "depth": 1},
        {"title": "Chapter 2", "page": 3, "depth": 0},
        {"title": "Chapter 2 - Notes", "page": 4, "depth": 1},
    ]
    segments = ex._build_outline_segments(nodes, total_pages=5)
    assert segments == [("Chapter 1", 0, 2), ("Chapter 2", 3, 4)]
    ex.close()


def test_min_segment_pages_merges_short_sections():
    ex = _extractor(min_segment_pages=3)
    nodes = [
        {"title": "Cover", "page": 0, "depth": 0},
        {"title": "Preface", "page": 1, "depth": 0},
        {"title": "Chapter 1", "page": 2, "depth": 0},
        {"title": "Chapter 2", "page": 10, "depth": 0},
    ]
    segments = ex._build_outline_segments(nodes, total_pages=20)
    assert segments == [
        ("Cover / Preface / Chapter 1", 0, 9),
        ("Chapter 2", 10, 19),
    ]
    ex.close()


def test_min_segment_pages_merges_trailing_short_section():
    ex = _extractor(min_segment_pages=3)
    nodes = [
        {"title": "Chapter 1", "page": 0, "depth": 0},
        {"title": "Index", "page": 10, "depth": 0},
    ]
    segments = ex._build_outline_segments(nodes, total_pages=11)
    assert segments == [("Chapter 1 / Index", 0, 10)]
    ex.close()


def test_parse_outline_nodes_tracks_depth_and_parent_title():
    ex = _extractor()

    class DummyReader:
        @staticmethod
        def get_destination_page_number(item):
            return item["page"]

    outline = [
        {"/Title": "A", "page": 0},
        [{"/Title": "B", "page": 1}, [{"/Title": "C", "page": 2}]],
        {"/Title": "D", "page": 3},
    ]
    nodes = ex.parse_outline_nodes(DummyReader(), outline)
    assert [(n["title"], n["depth"]) for n in nodes] == [
        ("A", 0),
        ("A - B", 1),
        ("A - B - C", 2),
        ("D", 0),
    ]
    ex.close()


def test_outline_filter_skips_boilerplate_title():
    ex = _extractor(outline_max_depth=0)
    nodes = [
        {"title": "Table of contents", "page": 0, "depth": 0},
        {"title": "Chapter 1", "page": 2, "depth": 0},
    ]
    segments = ex._build_outline_segments(nodes, total_pages=5)
    assert segments == [("Chapter 1", 2, 4)]
    ex.close()
