"""MP4 byte-probe routing and tail-fallback regression coverage."""
import unittest
from unittest.mock import patch
import media_probe


class MP4FallbackTests(unittest.TestCase):
    def test_magic_and_extension_share_same_tail_fallback(self):
        tail = b'x' * 64
        for head, name in ((b'1234ftyp' + b'0' * 8, 'unknown'), (b'unknown header!!', 'clip.mp4')):
            with self.subTest(name=name), patch.object(media_probe, 'parse_mp4', return_value=(0, 0, None)) as parser, \
                 patch.object(media_probe, 'parse_mp4_tail', return_value=(1920, 1080, 120)) as fallback:
                self.assertEqual(media_probe.probe_bytes(head, tail, name), {'w': 1920, 'h': 1080, 'duration': 120})
                parser.assert_called_once_with(head)
                fallback.assert_called_once_with(tail)

    def test_head_success_skips_tail_and_existing_duration_is_preserved(self):
        head, tail = b'1234ftyp' + b'0' * 8, b'x' * 64
        with patch.object(media_probe, 'parse_mp4', return_value=(1280, 720, 80)), \
             patch.object(media_probe, 'parse_mp4_tail') as fallback:
            self.assertEqual(media_probe.probe_bytes(head, tail), {'w': 1280, 'h': 720, 'duration': 80})
            fallback.assert_not_called()
        with patch.object(media_probe, 'parse_mp4', return_value=(0, 0, 80)), \
             patch.object(media_probe, 'parse_mp4_tail', return_value=(1920, 1080, 120)):
            self.assertEqual(media_probe.probe_bytes(head, tail), {'w': 1920, 'h': 1080, 'duration': 80})

    def test_short_tail_is_not_parsed_and_errors_remain_fail_soft(self):
        head = b'1234ftyp' + b'0' * 8
        with patch.object(media_probe, 'parse_mp4', return_value=(0, 0, None)), \
             patch.object(media_probe, 'parse_mp4_tail') as fallback:
            self.assertEqual(media_probe.probe_bytes(head, b'x' * 63), {})
            fallback.assert_not_called()
        with patch.object(media_probe, 'parse_mp4', side_effect=ValueError('broken')):
            self.assertEqual(media_probe.probe_bytes(head, b'x' * 64), {})
