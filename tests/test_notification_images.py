import ast
from contextlib import suppress
from pathlib import Path
from typing import Any
import unittest
from urllib.parse import parse_qs, urlparse


PLUGIN_PATH = Path(__file__).resolve().parents[1] / "main.py"


def load_image_selector():
    """独立验证实际选图方法，不依赖 AstrBot 运行环境或网络。"""
    tree = ast.parse(PLUGIN_PATH.read_text(encoding="utf-8"))
    notifier = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "DealNestNotifier")
    method = next(node for node in notifier.body if isinstance(node, ast.FunctionDef) and node.name == "_notification_image_url")
    namespace = {"Any": Any, "parse_qs": parse_qs, "urlparse": urlparse, "suppress": suppress}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(PLUGIN_PATH), "exec"), namespace)
    return namespace["_notification_image_url"]


select_image = load_image_selector()


class NotificationImageTests(unittest.TestCase):
    def test_new_thumbnail_uses_matching_proxy(self):
        proxy = "https://example.test/api/img-proxy?url=https%3A%2F%2Fcdn.example.test%2Flatest.jpg"
        self.assertEqual(select_image(None, {
            "authorLatestPostImageUrl": "https://cdn.example.test/latest.jpg",
            "imageUrl": proxy,
            "authorAvatarImageUrl": "https://cdn.example.test/avatar.jpg",
        }), proxy)

    def test_payload_thumbnail_is_compatible_with_old_api_avatar(self):
        self.assertEqual(select_image(None, {
            "imageUrl": "https://cdn.example.test/avatar.jpg",
            "authorAvatarImageUrl": "https://cdn.example.test/avatar.jpg",
            "payload": {"authorLatestPostImageUrl": "https://cdn.example.test/latest.jpg"},
        }), "https://cdn.example.test/latest.jpg")

    def test_thumbnail_cannot_be_overridden_by_avatar_or_cover(self):
        self.assertEqual(select_image(None, {
            "authorLatestPostImageUrl": "https://cdn.example.test/latest.jpg",
            "imageUrl": "https://cdn.example.test/avatar.jpg",
            "payload": {"imageUrl": "https://cdn.example.test/cover.jpg"},
        }), "https://cdn.example.test/latest.jpg")

    def test_missing_thumbnail_never_falls_back_to_any_avatar_field(self):
        avatar = "https://cdn.example.test/avatar.jpg"
        for payload in [None, {}, {
            "imageUrl": avatar,
            "authorAvatarImageUrl": avatar,
            "authorAvatarUrl": avatar,
        }]:
            with self.subTest(payload=payload):
                self.assertEqual(select_image(None, {
                    "imageUrl": avatar,
                    "authorAvatarImageUrl": avatar,
                    "authorAvatarUrl": avatar,
                    "payload": payload,
                }), "")

    def test_invalid_thumbnail_never_falls_back_to_image(self):
        for source in [None, "", "file:///tmp/latest.jpg", "not-a-url", 123]:
            with self.subTest(source=source):
                self.assertEqual(select_image(None, {
                    "authorLatestPostImageUrl": source,
                    "imageUrl": "https://cdn.example.test/avatar.jpg",
                    "authorAvatarImageUrl": "https://cdn.example.test/avatar.jpg",
                }), "")


if __name__ == "__main__":
    unittest.main()
