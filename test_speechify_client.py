import base64
import io
import json
import unittest
import wave
from unittest.mock import patch
import speechify_client as client

class Tests(unittest.TestCase):
    def test_catalog_pagination_and_order(self):
        pages = [
            {"voices": [{"id": "es", "display_name": "Voz", "locale": "es-ES"}], "has_more": True, "next_cursor": "next"},
            {"voices": [{"id": "mx", "display_name": "Alejandro", "locale": "es-MX"}], "has_more": False},
        ]
        with patch.object(client, "_request", side_effect=pages) as request:
            voices = client.list_voices("private")
        self.assertEqual([v["id"] for v in voices], ["mx", "es"])
        self.assertIn("cursor=next", request.call_args_list[1].args[1])

    def test_valid_audio_and_payload(self):
        data = io.BytesIO()
        with wave.open(data, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24000)
            wav.writeframes(b"\\x10\\x00" * 4800)
        with patch.object(client, "_request", return_value={"audio_data": base64.b64encode(data.getvalue()).decode()}) as request:
            self.assertEqual(client.synthesize("private", "Hola María", "mx"), data.getvalue())
        self.assertEqual(request.call_args.args[2]["input"], "Hola María")
        self.assertEqual(request.call_args.args[2]["audio_format"], "wav")

    def test_invalid_audio_and_text(self):
        with patch.object(client, "_request", return_value={"audio_data": base64.b64encode(b"invalid").decode()}):
            with self.assertRaises(RuntimeError): client.synthesize("private", "Hola", "mx")
        with self.assertRaises(ValueError): client.synthesize("private", "", "mx")
        with self.assertRaises(ValueError): client.synthesize("private", "x" * 2001, "mx")

if __name__ == "__main__":
    unittest.main()
